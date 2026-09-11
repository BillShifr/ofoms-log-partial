"""Тесты core: парольная политика, блокировка, токены, журнал событий."""

import datetime
import os
import re
import subprocess
import sys
from pathlib import Path
from unittest import mock

import jwt
from django.conf import settings
from django.contrib.auth import authenticate, get_user_model
from django.contrib.auth.signals import user_login_failed
from django.core.exceptions import ValidationError
from django.db import DatabaseError, IntegrityError, connection, transaction
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.core.models import ConsumedToken, EventLog, log_event
from apps.core.tokens import (
    EmployeeRepository,
    consume_token,
    decode_token,
    issue_token,
    resolve_user,
)
from apps.core.validators import ComplexityPasswordValidator

User = get_user_model()


class ProductionSettingsTests(TestCase):
    def _import_settings(self, database_password, code="import config.settings.prod"):
        environment = os.environ.copy()
        environment.pop("TRUST_PROXY_SSL_HEADER", None)
        environment.update(
            {
                "DJANGO_SETTINGS_MODULE": "config.settings.prod",
                "SECRET_KEY": "test-secret-key-with-more-than-fifty-characters-123456789",
                "JWT_SECRET": "test-jwt-secret-with-more-than-fifty-characters-987654321",
                "DB_PASSWORD": database_password,
            }
        )
        return subprocess.run(
            [sys.executable, "-c", code],
            cwd=settings.BASE_DIR,
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )

    def test_production_rejects_missing_or_default_database_password(self):
        for password in ("", "ejournal", "postgres", "password"):
            with self.subTest(password=password):
                result = self._import_settings(password)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("DB_PASSWORD", result.stderr)

    def test_production_accepts_strong_database_password(self):
        result = self._import_settings("database-secret-4827-strong")
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_production_trusts_tls_terminator_scheme_by_default(self):
        result = self._import_settings(
            "database-secret-4827-strong",
            "from config.settings.prod import SECURE_PROXY_SSL_HEADER; "
            "print(SECURE_PROXY_SSL_HEADER)",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("HTTP_X_FORWARDED_PROTO", result.stdout)

    def test_proxied_https_health_request_does_not_redirect(self):
        result = self._import_settings(
            "database-secret-4827-strong",
            "import django; django.setup(); "
            "from django.test import Client; "
            "print(Client().get('/healthz', HTTP_HOST='localhost', "
            "HTTP_X_FORWARDED_PROTO='https').status_code)",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "200")

    def test_liveness_and_readiness_are_uncached_and_readiness_queries_database(self):
        with self.assertNumQueries(0):
            liveness = self.client.get("/healthz")
        with self.assertNumQueries(1):
            readiness = self.client.get("/readyz")

        self.assertEqual(liveness.status_code, 200)
        self.assertEqual(liveness.content, b"ok")
        self.assertEqual(readiness.status_code, 200)
        self.assertEqual(readiness.content, b"ready")
        self.assertEqual(liveness.headers["Cache-Control"], "no-store")
        self.assertEqual(readiness.headers["Cache-Control"], "no-store")

    def test_readiness_fails_closed_when_database_is_unavailable(self):
        with mock.patch.object(connection, "cursor", side_effect=DatabaseError("offline")):
            response = self.client.get("/readyz")

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.content, b"unavailable")
        self.assertEqual(response.headers["Cache-Control"], "no-store")

    def test_compose_binds_web_to_loopback_by_default(self):
        compose = (settings.BASE_DIR / "docker-compose.yml").read_text()
        example = (settings.BASE_DIR / ".env.example").read_text()

        self.assertIn("${WEB_BIND_ADDRESS:-127.0.0.1}:8000:8000", compose)
        self.assertIn("TRUST_PROXY_SSL_HEADER: ${TRUST_PROXY_SSL_HEADER:-True}", compose)
        self.assertIn("c.request('GET','/readyz',headers={'X-Forwarded-Proto':'https'})", compose)
        self.assertIn("r.status == 200", compose)
        self.assertIn("SESSION_COOKIE_SECURE=True", example)
        self.assertIn("SECURE_SSL_REDIRECT=True", example)

    def test_build_executables_are_pinned_to_immutable_revisions(self):
        dockerfile = (settings.BASE_DIR / "Dockerfile").read_text()
        compose = (settings.BASE_DIR / "docker-compose.yml").read_text()
        workflow = (settings.BASE_DIR / ".github" / "workflows" / "ci.yml").read_text()

        self.assertIn("FROM python:3.13-slim@sha256:", dockerfile)
        self.assertIn("--from=ghcr.io/astral-sh/uv@sha256:", dockerfile)
        self.assertNotIn("uv:latest", dockerfile)
        self.assertIn("image: postgres:16-alpine@sha256:", compose)
        action_refs = re.findall(r"^\s*-?\s*uses:\s+([^\s#]+)", workflow, re.MULTILINE)
        self.assertTrue(action_refs)
        self.assertEqual(
            [ref for ref in action_refs if not re.fullmatch(r"[^@]+@[0-9a-f]{40}", ref)],
            [],
        )

    def test_application_image_uses_unprivileged_runtime_user(self):
        dockerfile = (settings.BASE_DIR / "Dockerfile").read_text()
        compose = (settings.BASE_DIR / "docker-compose.yml").read_text()

        self.assertIn("useradd --uid 10001", dockerfile)
        self.assertIn("chown -R app:app /app/media /app/exchange", dockerfile)
        self.assertRegex(dockerfile, r"(?m)^USER 10001:10001$")
        self.assertIn("condition: service_completed_successfully", compose)
        self.assertIn('user: "0:0"', compose)
        self.assertIn("chown -R 10001:10001 /app/media /app/exchange", compose)

    def test_compose_services_restart_and_receive_termination_signals(self):
        compose = (settings.BASE_DIR / "docker-compose.yml").read_text()

        self.assertEqual(compose.count("restart: unless-stopped"), 3)
        self.assertEqual(compose.count("stop_grace_period: 75s"), 2)
        self.assertEqual(compose.count("init: true"), 2)
        self.assertIn("exec .venv/bin/gunicorn", compose)
        self.assertIn(
            'command: [".venv/bin/python", "manage.py", "run_scheduler", "--interval", "60"]',
            compose,
        )
        self.assertNotIn("while true", compose)

    def test_uv_sync_treats_application_as_virtual_project(self):
        project = (settings.BASE_DIR / "pyproject.toml").read_text()
        lockfile = (settings.BASE_DIR / "uv.lock").read_text()

        self.assertIn("[tool.uv]", project)
        self.assertIn("package = false", project)
        self.assertIn('name = "ejournal-portal-tfoms"', lockfile)
        self.assertIn('source = { virtual = "." }', lockfile)


class ComplexityPasswordValidatorTests(TestCase):
    def setUp(self):
        self.validator = ComplexityPasswordValidator()

    def test_all_classes_ok(self):
        self.validator.validate("Abcd1234!")  # не должно бросать
        self.validator.validate("Крато?!123")  # не должно бросать

    def test_missing_classes_rejected(self):
        with self.assertRaises(ValidationError):
            self.validator.validate("abcdefgh")

    def test_help_text(self):
        self.assertIn("строчные и прописные буквы", self.validator.get_help_text())


class FailedLoginLockTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="operator", password="GoodPass!1", org=81000
        )

    def test_lock_after_limit(self):
        limit = 10
        for _ in range(limit):
            self.user.record_failed_login()
        self.assertTrue(self.user.is_locked)
        # аутентификация заблокированного возвращает None
        got = authenticate(username="operator", password="GoodPass!1")
        self.assertIsNone(got)

    def test_reset_failed_logins(self):
        self.user.record_failed_login()
        self.user.record_failed_login()
        self.user.reset_failed_logins()
        self.assertEqual(self.user.failed_attempts, 0)
        self.assertFalse(self.user.is_locked)

    def test_login_failed_signal_increments_counter(self):
        for _ in range(3):
            user_login_failed.send(
                sender=User.__name__, credentials={"username": "operator"},
                request=None,
            )
        self.user.refresh_from_db()
        self.assertEqual(self.user.failed_attempts, 3)


class TokenTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="tokenuser", password="GoodPass!1", org=81008
        )

    def test_issue_decode_roundtrip(self):
        token = issue_token(self.user)
        payload = decode_token(token)
        self.assertEqual(payload["username"], "tokenuser")
        self.assertEqual(payload["sub"], str(self.user.guid))
        self.assertTrue(payload["jti"])

    @override_settings(JWT_AUDIENCE="trusted-portal")
    def test_configured_audience_is_used_for_issue_and_decode(self):
        token = issue_token(self.user)

        self.assertEqual(decode_token(token)["aud"], "trusted-portal")
        with self.assertRaises(jwt.InvalidAudienceError):
            decode_token(token, audience="another-system")

    def test_resolve_user(self):
        token = issue_token(self.user)
        self.assertEqual(resolve_user(token).pk, self.user.pk)

    def test_expired_token_rejected(self):
        expired = issue_token(self.user, ttl=-10)
        self.assertIsNone(resolve_user_catching(expired))

    def test_zero_ttl_is_not_replaced_by_default(self):
        token = issue_token(self.user, ttl=0)
        self.assertIsNone(resolve_user_catching(token))

    def test_resolve_user_uses_repository_adapter(self):
        class Repository(EmployeeRepository):
            def get_by_guid(self, guid):
                self.guid = guid
                return self.user

        repository = Repository()
        repository.user = self.user
        resolved = resolve_user(issue_token(self.user), repository=repository)
        self.assertEqual(resolved, self.user)
        self.assertEqual(repository.guid, str(self.user.guid))

    def test_token_identifier_is_consumed_once(self):
        payload = decode_token(issue_token(self.user))

        self.assertTrue(consume_token(payload))
        self.assertFalse(consume_token(payload))
        self.assertEqual(ConsumedToken.objects.count(), 1)


class TokenLoginTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="sso-user", password="GoodPass!1", org=81008
        )
        self.url = reverse("core:token_login")

    def test_valid_form_token_creates_session(self):
        response = self.client.post(self.url, {"token": issue_token(self.user)})
        self.assertRedirects(response, reverse("journal:list"), fetch_redirect_response=False)
        self.assertEqual(int(self.client.session["_auth_user_id"]), self.user.pk)
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        self.assertEqual(response.headers["Referrer-Policy"], "no-referrer")

    def test_valid_bearer_token_creates_session(self):
        response = self.client.post(
            self.url,
            HTTP_AUTHORIZATION=f"Bearer {issue_token(self.user)}",
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(int(self.client.session["_auth_user_id"]), self.user.pk)

    def test_token_replay_is_rejected(self):
        token = issue_token(self.user)
        first = self.client.post(self.url, {"token": token})
        second_client = Client()
        replay = second_client.post(self.url, {"token": token})

        self.assertEqual(first.status_code, 302)
        self.assertEqual(replay.status_code, 403)
        self.assertNotIn("_auth_user_id", second_client.session)
        self.assertEqual(ConsumedToken.objects.count(), 1)

    def test_signed_token_without_required_jti_is_rejected(self):
        now = datetime.datetime.now(tz=datetime.UTC)
        token = jwt.encode(
            {
                "sub": str(self.user.guid),
                "aud": "ejournal",
                "iat": now,
                "exp": now + datetime.timedelta(minutes=1),
            },
            settings.JWT_SECRET,
            algorithm=settings.JWT_ALGORITHM,
        )

        response = self.client.post(self.url, {"token": token})
        self.assertEqual(response.status_code, 403)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_unsafe_next_is_ignored(self):
        response = self.client.post(
            self.url,
            {"token": issue_token(self.user), "next": "https://attacker.invalid/steal"},
        )
        self.assertEqual(response.url, reverse("journal:list"))

    def test_safe_next_is_used(self):
        response = self.client.post(
            self.url,
            {"token": issue_token(self.user), "next": "/reports/"},
        )
        self.assertEqual(response.url, "/reports/")

    def test_invalid_token_is_rejected_without_session(self):
        response = self.client.post(self.url, {"token": "not-a-jwt"})
        self.assertEqual(response.status_code, 403)
        self.assertNotIn("_auth_user_id", self.client.session)
        self.assertNotContains(response, "not-a-jwt", status_code=403)

    def test_signed_token_with_invalid_subject_is_rejected(self):
        token = jwt.encode(
            {"sub": "not-a-guid", "aud": "ejournal"},
            settings.JWT_SECRET,
            algorithm=settings.JWT_ALGORITHM,
        )
        response = self.client.post(self.url, {"token": token})
        self.assertEqual(response.status_code, 403)

    def test_locked_and_inactive_users_are_rejected(self):
        for field, value in (
            ("is_active", False),
            ("lock_until", timezone.now().replace(year=9999)),
        ):
            setattr(self.user, field, value)
            self.user.save(update_fields=[field])
            response = self.client.post(self.url, {"token": issue_token(self.user)})
            self.assertEqual(response.status_code, 403)
            self.client.logout()
            setattr(self.user, field, True if field == "is_active" else None)
            self.user.save(update_fields=[field])

    def test_endpoint_is_post_only_and_rejects_malformed_authorization(self):
        self.assertEqual(self.client.get(self.url).status_code, 405)
        response = self.client.post(
            self.url,
            {"token": issue_token(self.user)},
            HTTP_AUTHORIZATION="Basic credentials",
        )
        self.assertEqual(response.status_code, 400)


def resolve_user_catching(token):
    from apps.core.tokens import resolve_user

    try:
        return resolve_user(token)
    except Exception:
        return None


class EventLogTests(TestCase):
    def test_create_and_log_event(self):
        entry = EventLog.objects.create(
            module="test", event_type=EventLog.EventType.OTHER, target="x"
        )
        self.assertTrue(entry.pk)
        self.assertEqual(entry.module, "test")
        self.assertEqual(str(entry.user_id), "None" if entry.user_id is None else str(entry.user_id))
        self.assertEqual(EventLog.objects.count(), 1)

    def _assert_invalid_event_rejected(self, **overrides):
        values = {"module": "test", "event_type": EventLog.EventType.OTHER}
        values.update(overrides)
        with self.assertRaises(IntegrityError), transaction.atomic():
            EventLog.objects.create(**values)

    def test_database_rejects_unknown_event_type(self):
        self._assert_invalid_event_rejected(event_type="unknown")

    def test_database_rejects_unknown_result(self):
        self._assert_invalid_event_rejected(result="unknown")

    def test_database_rejects_blank_module(self):
        self._assert_invalid_event_rejected(module="")

    def test_database_rejects_incomplete_completion_pair(self):
        self._assert_invalid_event_rejected(duration_ms=1)

    def test_database_rejects_reverse_timeline(self):
        started = timezone.now()
        with self.assertRaises(IntegrityError), transaction.atomic():
            EventLog.objects.create(
                module="test",
                event_type=EventLog.EventType.OTHER,
                started_at=started,
                finished_at=started - datetime.timedelta(seconds=1),
                duration_ms=0,
            )

    def test_point_event_has_consistent_end_and_duration(self):
        entry = log_event(module="test", event_type=EventLog.EventType.CREATE)
        self.assertEqual(entry.finished_at, entry.started_at)
        self.assertEqual(entry.duration_ms, 0)

    def test_pending_event_is_completed_without_explicit_duration(self):
        entry = log_event(
            module="test", event_type=EventLog.EventType.TASK, pending=True
        )
        self.assertIsNone(entry.finished_at)
        completed = log_event(
            module="test", event_type=EventLog.EventType.TASK, obj=entry
        )
        self.assertIsNotNone(completed.finished_at)
        self.assertIsNotNone(completed.duration_ms)


class AuthenticationAuditTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="audit-user", password="GoodPass!1", org=81000
        )

    def test_successful_login_is_recorded_with_authenticated_user(self):
        response = self.client.post(
            reverse("login"),
            {"username": self.user.username, "password": "GoodPass!1"},
        )

        self.assertEqual(response.status_code, 302)
        event = EventLog.objects.get(target="POST /accounts/login/")
        self.assertEqual(event.event_type, EventLog.EventType.LOGIN)
        self.assertEqual(event.result, EventLog.Result.OK)
        self.assertEqual(event.user, self.user)

    def test_failed_login_is_recorded_without_user(self):
        response = self.client.post(
            reverse("login"),
            {"username": self.user.username, "password": "wrong-password"},
        )

        self.assertEqual(response.status_code, 200)
        event = EventLog.objects.get(target="POST /accounts/login/")
        self.assertEqual(event.event_type, EventLog.EventType.LOGIN_FAILED)
        self.assertEqual(event.result, EventLog.Result.FAILED)
        self.assertIsNone(event.user)

    def test_token_login_is_recorded_as_authenticated_login(self):
        response = self.client.post(
            reverse("core:token_login"), {"token": issue_token(self.user)}
        )

        self.assertEqual(response.status_code, 302)
        event = EventLog.objects.get(target="POST /accounts/token-login/")
        self.assertEqual(event.event_type, EventLog.EventType.LOGIN)
        self.assertEqual(event.result, EventLog.Result.OK)
        self.assertEqual(event.user, self.user)

    def test_logout_keeps_pre_request_user_as_actor(self):
        self.client.force_login(self.user)
        response = self.client.post(reverse("logout"))

        self.assertEqual(response.status_code, 302)
        event = EventLog.objects.get(target="POST /accounts/logout/")
        self.assertEqual(event.event_type, EventLog.EventType.LOGOUT)
        self.assertEqual(event.user, self.user)


class FoldTests(TestCase):
    """Регистронезависимый поиск, не зависящий от локали БД (PRD v3 §2.3.2)."""

    def test_fold_cyrillic_and_latin(self):
        from apps.core.fold import fold

        self.assertEqual(fold("Иванов-ИВАН 123AbC"), "иванов-иван 123abc")
        self.assertEqual(fold("ёёЁ"), "ёёё")

    def test_contains_folded_finds_substring(self):
        from apps.core.fold import contains_folded
        from apps.core.models import EventLog

        EventLog.objects.create(
            module="test", event_type=EventLog.EventType.OTHER, target="ИСТЕЦ: Петров И."
        )
        qs = contains_folded(
            EventLog.objects.all(), "target", "истец: петров", "fold_target"
        )
        self.assertEqual(qs.count(), 1)

    def test_filter_contains_any_matches_any_field(self):
        from apps.core.fold import filter_contains_any
        from apps.core.models import EventLog

        EventLog.objects.create(
            module="test", event_type=EventLog.EventType.OTHER, target="иванов-иван"
        )
        qs = filter_contains_any(
            EventLog.objects.all(),
            ("target", "module"),
            "ИВАНОВ",
            prefix="any_",
        )
        self.assertEqual(qs.count(), 1)

    def test_blank_value_is_noop(self):
        from apps.core.fold import contains_folded

        self.assertEqual(contains_folded("qs", "target", "   ", None), "qs")


class ErrorPageTests(TestCase):
    def test_not_found_uses_portal_error_page(self):
        response = self.client.get("/definitely-missing-page/")
        self.assertEqual(response.status_code, 404)
        self.assertContains(response, "Страница не найдена", status_code=404)


class TemplateHygieneTests(TestCase):
    def test_templates_do_not_embed_style_or_event_attributes(self):
        templates_root = Path(settings.BASE_DIR) / "templates"
        violations = []
        forbidden = ('style="', "style='", 'onclick="', 'onchange="', 'onsubmit="')
        for template in templates_root.rglob("*.html"):
            text = template.read_text(encoding="utf-8-sig")
            if any(marker in text.lower() for marker in forbidden):
                violations.append(str(template.relative_to(templates_root)))
        self.assertEqual(violations, [])

    def test_templates_do_not_embed_executable_inline_scripts(self):
        templates_root = Path(settings.BASE_DIR) / "templates"
        violations = []
        inline_script = re.compile(r"<script(?![^>]*\bsrc\s*=)[^>]*>", re.IGNORECASE)
        for template in templates_root.rglob("*.html"):
            text = template.read_text(encoding="utf-8-sig")
            if inline_script.search(text):
                violations.append(str(template.relative_to(templates_root)))
        self.assertEqual(violations, [])

    def test_scripts_do_not_write_inline_styles(self):
        scripts_root = Path(settings.BASE_DIR) / "static" / "js"
        violations = []
        inline_style = re.compile(r"\.style\b|setAttribute\(\s*['\"]style['\"]")
        for script in scripts_root.rglob("*.js"):
            if inline_style.search(script.read_text(encoding="utf-8-sig")):
                violations.append(str(script.relative_to(scripts_root)))
        self.assertEqual(violations, [])

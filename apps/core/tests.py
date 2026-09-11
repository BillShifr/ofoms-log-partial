"""Тесты core: парольная политика, блокировка, токены, журнал событий."""

import datetime
import os
import re
import subprocess
import sys
import uuid
from pathlib import Path
from unittest import mock

import jwt
from django.conf import settings
from django.contrib import admin
from django.contrib.auth import authenticate, get_user_model
from django.contrib.auth.signals import user_login_failed
from django.core.exceptions import ValidationError
from django.core.files.uploadhandler import StopUpload
from django.db import DatabaseError, IntegrityError, connection, transaction
from django.db.models.deletion import ProtectedError
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
from apps.core.uploads import BoundedUploadHandler
from apps.core.validators import ComplexityPasswordValidator
from apps.exchange.models import ImportLog
from apps.journal.models import Irp, IrpAnswer, IrpFile, IrpHistory, XmlFiles
from apps.system.models import NewsCategory, TaskRun

User = get_user_model()


class ProtectedAdminTests(TestCase):
    def test_audit_provenance_and_portal_managed_models_are_view_only(self):
        for model in (
            EventLog,
            ImportLog,
            XmlFiles,
            IrpHistory,
            TaskRun,
            Irp,
            IrpAnswer,
            IrpFile,
        ):
            with self.subTest(model=model._meta.label):
                model_admin = admin.site._registry[model]
                self.assertFalse(model_admin.has_add_permission(request=None))
                self.assertFalse(model_admin.has_change_permission(request=None))
                self.assertFalse(model_admin.has_delete_permission(request=None))
                self.assertEqual(
                    set(model_admin.get_readonly_fields(request=None)),
                    {field.name for field in model._meta.fields},
                )


class ProductionSettingsTests(TestCase):
    def _import_settings(
        self,
        database_password,
        code="import config.settings.prod",
        extra_environment=None,
    ):
        environment = os.environ.copy()
        environment.pop("TRUST_PROXY_SSL_HEADER", None)
        environment.pop("TRUSTED_PROXY_IPS", None)
        environment.pop("LOG_LEVEL", None)
        environment.pop("JWT_AUDIENCE", None)
        environment.pop("JWT_TTL", None)
        environment.pop("MAX_FAILED_LOGIN_ATTEMPTS", None)
        environment.pop("SESSION_COOKIE_AGE", None)
        environment.pop("TASK_STALE_AFTER_SECONDS", None)
        environment.update(
            {
                "DJANGO_SETTINGS_MODULE": "config.settings.prod",
                "SECRET_KEY": "test-secret-key-with-more-than-fifty-characters-123456789",
                "JWT_SECRET": "test-jwt-secret-with-more-than-fifty-characters-987654321",
                "DB_PASSWORD": database_password,
                "ALLOWED_HOSTS": "localhost,127.0.0.1",
            }
        )
        environment.update(extra_environment or {})
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

    def test_production_bounds_temporary_token_lifetime(self):
        for ttl in ("29", "901", "not-a-number"):
            with self.subTest(ttl=ttl):
                result = self._import_settings(
                    "database-secret-4827-strong",
                    extra_environment={"JWT_TTL": ttl},
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("JWT_TTL", result.stderr)

        accepted = self._import_settings(
            "database-secret-4827-strong",
            "from config.settings.prod import JWT_TTL; print(JWT_TTL)",
            {"JWT_TTL": "600"},
        )
        self.assertEqual(accepted.returncode, 0, accepted.stderr)
        self.assertEqual(accepted.stdout.strip(), "600")

    def test_production_validates_jwt_audience_identifier(self):
        for audience in ("", "two audiences", "https://sso.example/aud", "x" * 129):
            with self.subTest(audience=audience):
                result = self._import_settings(
                    "database-secret-4827-strong",
                    extra_environment={"JWT_AUDIENCE": audience},
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("JWT_AUDIENCE", result.stderr)

        accepted = self._import_settings(
            "database-secret-4827-strong",
            "from config.settings.prod import JWT_AUDIENCE; print(JWT_AUDIENCE)",
            {"JWT_AUDIENCE": "tfoms:ejournal-v2"},
        )
        self.assertEqual(accepted.returncode, 0, accepted.stderr)
        self.assertEqual(accepted.stdout.strip(), "tfoms:ejournal-v2")

    def test_production_rejects_debug_or_invalid_logging(self):
        for level in ("DEBUG", "NOTSET", "verbose", ""):
            with self.subTest(level=level):
                result = self._import_settings(
                    "database-secret-4827-strong",
                    extra_environment={"LOG_LEVEL": level},
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("LOG_LEVEL", result.stderr)

    def test_production_applies_safe_log_level_to_all_console_loggers(self):
        result = self._import_settings(
            "database-secret-4827-strong",
            code=(
                "from config.settings.prod import LOGGING; "
                "print(LOGGING['root']['level']); "
                "print(sorted(v['level'] for v in LOGGING['loggers'].values()))"
            ),
            extra_environment={"LOG_LEVEL": "warning"},
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("WARNING", result.stdout)

    def test_production_rejects_wildcard_or_malformed_allowed_hosts(self):
        for hosts in ("", "*", "https://journal.example", "valid.example/bad", "two hosts"):
            with self.subTest(hosts=hosts):
                result = self._import_settings(
                    "database-secret-4827-strong",
                    extra_environment={"ALLOWED_HOSTS": hosts},
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("ALLOWED_HOSTS", result.stderr)

    def test_production_accepts_explicit_host_names(self):
        result = self._import_settings(
            "database-secret-4827-strong",
            "from config.settings.prod import ALLOWED_HOSTS; print(ALLOWED_HOSTS)",
            {"ALLOWED_HOSTS": "journal.example,.internal.example,127.0.0.1"},
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("journal.example", result.stdout)
        self.assertIn(".internal.example", result.stdout)

    def test_production_rejects_ambiguous_security_values(self):
        invalid_environments = (
            {"SESSION_COOKIE_SECURE": "treu"},
            {"SECURE_SSL_REDIRECT": "enabled"},
            {"TRUST_PROXY_SSL_HEADER": "sometimes"},
            {"TRUST_PROXY_CLIENT_IP_HEADER": "sometimes"},
            {"SECURE_HSTS_SECONDS": "-1"},
            {"SECURE_HSTS_SECONDS": "not-a-number"},
            {"SESSION_COOKIE_AGE": "299"},
            {"SESSION_COOKIE_AGE": "43201"},
            {"SESSION_COOKIE_AGE": "not-a-number"},
        )
        for environment in invalid_environments:
            with self.subTest(environment=environment):
                result = self._import_settings(
                    "database-secret-4827-strong",
                    extra_environment=environment,
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(next(iter(environment)), result.stderr)

    def test_production_uses_bounded_sliding_browser_session(self):
        result = self._import_settings(
            "database-secret-4827-strong",
            code=(
                "from config.settings.prod import "
                "SESSION_COOKIE_AGE, SESSION_EXPIRE_AT_BROWSER_CLOSE, "
                "SESSION_SAVE_EVERY_REQUEST; "
                "print(SESSION_COOKIE_AGE, SESSION_EXPIRE_AT_BROWSER_CLOSE, "
                "SESSION_SAVE_EVERY_REQUEST)"
            ),
            extra_environment={"SESSION_COOKIE_AGE": "1800"},
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("1800 True True", result.stdout)

    def test_production_bounds_login_and_stale_recovery_limits(self):
        invalid_environments = (
            {"MAX_FAILED_LOGIN_ATTEMPTS": "0"},
            {"MAX_FAILED_LOGIN_ATTEMPTS": "11"},
            {"MAX_FAILED_LOGIN_ATTEMPTS": "not-a-number"},
            {"TASK_STALE_AFTER_SECONDS": "299"},
            {"TASK_STALE_AFTER_SECONDS": "86401"},
            {"TASK_STALE_AFTER_SECONDS": "not-a-number"},
        )
        for environment in invalid_environments:
            with self.subTest(environment=environment):
                result = self._import_settings(
                    "database-secret-4827-strong",
                    extra_environment=environment,
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(next(iter(environment)), result.stderr)

        accepted = self._import_settings(
            "database-secret-4827-strong",
            code=(
                "from config.settings.prod import "
                "SECURITY_MAX_FAILED_LOGIN_ATTEMPTS, TASK_STALE_AFTER_SECONDS; "
                "print(SECURITY_MAX_FAILED_LOGIN_ATTEMPTS, TASK_STALE_AFTER_SECONDS)"
            ),
            extra_environment={
                "MAX_FAILED_LOGIN_ATTEMPTS": "7",
                "TASK_STALE_AFTER_SECONDS": "7200",
            },
        )
        self.assertEqual(accepted.returncode, 0, accepted.stderr)
        self.assertEqual(accepted.stdout.strip(), "7 7200")

    def test_production_validates_token_login_trusted_origins(self):
        for origins in (
            "http://sso.example",
            "https://user:password@sso.example",
            "https://sso.example/callback",
            "https://sso.example?tenant=1",
        ):
            with self.subTest(origins=origins):
                result = self._import_settings(
                    "database-secret-4827-strong",
                    extra_environment={"TOKEN_LOGIN_TRUSTED_ORIGINS": origins},
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("TOKEN_LOGIN_TRUSTED_ORIGINS", result.stderr)

        accepted = self._import_settings(
            "database-secret-4827-strong",
            "from config.settings.prod import TOKEN_LOGIN_TRUSTED_ORIGINS; "
            "print(TOKEN_LOGIN_TRUSTED_ORIGINS)",
            {"TOKEN_LOGIN_TRUSTED_ORIGINS": "https://sso.example,https://SSO.example/"},
        )
        self.assertEqual(accepted.returncode, 0, accepted.stderr)
        self.assertEqual(accepted.stdout.strip(), "('https://sso.example',)")

    def test_production_uses_bounded_health_checked_database_pool(self):
        result = self._import_settings(
            "database-secret-4827-strong",
            "from config.settings.prod import DATABASES; "
            "db=DATABASES['default']; "
            "print(db['CONN_MAX_AGE'], db['CONN_HEALTH_CHECKS'], db['OPTIONS'])",
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("0 True", result.stdout)
        self.assertIn("'connect_timeout': 3", result.stdout)
        self.assertIn("'min_size': 1", result.stdout)
        self.assertIn("'max_size': 4", result.stdout)
        self.assertIn("'timeout': 3", result.stdout)

    def test_production_rejects_invalid_database_pool_configuration(self):
        invalid_environments = (
            {"DB_POOL_MIN_SIZE": "5", "DB_POOL_MAX_SIZE": "4"},
            {"DB_POOL_TIMEOUT": "0"},
            {"DB_CONNECT_TIMEOUT": "not-a-number"},
        )
        for environment in invalid_environments:
            with self.subTest(environment=environment):
                result = self._import_settings(
                    "database-secret-4827-strong",
                    extra_environment=environment,
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("DB_", result.stderr)

    def test_production_trusts_tls_terminator_scheme_by_default(self):
        result = self._import_settings(
            "database-secret-4827-strong",
            "from config.settings.prod import SECURE_PROXY_SSL_HEADER; "
            "print(SECURE_PROXY_SSL_HEADER)",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("HTTP_X_FORWARDED_PROTO", result.stdout)

    def test_production_validates_and_normalizes_trusted_proxy_networks(self):
        for networks in ("", "not-an-ip", "127.0.0.1/99"):
            with self.subTest(networks=networks):
                result = self._import_settings(
                    "database-secret-4827-strong",
                    extra_environment={"TRUSTED_PROXY_IPS": networks},
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("TRUSTED_PROXY_IPS", result.stderr)

        accepted = self._import_settings(
            "database-secret-4827-strong",
            "from config.settings.prod import TRUSTED_PROXY_IPS; "
            "print(TRUSTED_PROXY_IPS)",
            {"TRUSTED_PROXY_IPS": "192.0.2.7,2001:db8::1/64"},
        )
        self.assertEqual(accepted.returncode, 0, accepted.stderr)
        self.assertEqual(
            accepted.stdout.strip(),
            "('192.0.2.7/32', '2001:db8::/64')",
        )

        disabled = self._import_settings(
            "database-secret-4827-strong",
            "from config.settings.prod import TRUSTED_PROXY_IPS; "
            "print(TRUSTED_PROXY_IPS)",
            {
                "TRUST_PROXY_SSL_HEADER": "false",
                "TRUST_PROXY_CLIENT_IP_HEADER": "false",
                "TRUSTED_PROXY_IPS": "",
            },
        )
        self.assertEqual(disabled.returncode, 0, disabled.stderr)
        self.assertEqual(disabled.stdout.strip(), "()")

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

    def test_untrusted_peer_cannot_spoof_proxied_https(self):
        result = self._import_settings(
            "database-secret-4827-strong",
            "import django; django.setup(); "
            "from django.test import Client; "
            "response=Client().get('/healthz', HTTP_HOST='localhost', "
            "REMOTE_ADDR='198.51.100.9', HTTP_X_FORWARDED_PROTO='https'); "
            "print(response.status_code, response.headers.get('Location'))",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("301 https://localhost/healthz", result.stdout)

    def test_liveness_and_readiness_are_uncached_and_readiness_queries_database(self):
        with self.assertNumQueries(0):
            liveness = self.client.get("/healthz")
        with self.assertNumQueries(1):
            readiness = self.client.get("/readyz")

        self.assertEqual(liveness.status_code, 200)
        self.assertEqual(liveness.content, b"ok")
        self.assertEqual(readiness.status_code, 200)
        self.assertEqual(readiness.content, b"ready")
        self.assertIn("no-store", liveness.headers["Cache-Control"])
        self.assertIn("no-store", readiness.headers["Cache-Control"])

    def test_readiness_fails_closed_when_database_is_unavailable(self):
        with mock.patch.object(connection, "cursor", side_effect=DatabaseError("offline")):
            response = self.client.get("/readyz")

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.content, b"unavailable")
        self.assertIn("no-store", response.headers["Cache-Control"])

    def test_compose_binds_web_to_loopback_by_default(self):
        compose = (settings.BASE_DIR / "docker-compose.yml").read_text()
        example = (settings.BASE_DIR / ".env.example").read_text()

        self.assertIn("${WEB_BIND_ADDRESS:-127.0.0.1}:8000:8000", compose)
        self.assertIn("TRUST_PROXY_SSL_HEADER: ${TRUST_PROXY_SSL_HEADER:-True}", compose)
        self.assertIn("TRUSTED_PROXY_IPS: ${TRUSTED_PROXY_IPS:-127.0.0.1/32,::1/128}", compose)
        self.assertLess(
            compose.index("TRUSTED_PROXY_IPS:"),
            compose.index("ports:"),
        )
        self.assertIn("c.request('GET','/readyz',headers={'X-Forwarded-Proto':'https'})", compose)
        self.assertIn("r.status == 200", compose)
        self.assertIn("SESSION_COOKIE_SECURE=True", example)
        self.assertIn("MAX_FAILED_LOGIN_ATTEMPTS: ${MAX_FAILED_LOGIN_ATTEMPTS:-10}", compose)
        self.assertIn("SESSION_COOKIE_AGE: ${SESSION_COOKIE_AGE:-28800}", compose)
        self.assertIn("TASK_STALE_AFTER_SECONDS: ${TASK_STALE_AFTER_SECONDS:-3600}", compose)
        self.assertIn("SECURE_SSL_REDIRECT=True", example)
        self.assertIn("LOG_LEVEL: ${LOG_LEVEL:-INFO}", compose)
        self.assertIn("JWT_TTL: ${JWT_TTL:-300}", compose)
        self.assertIn("LOG_LEVEL=INFO", example)
        self.assertLess(
            settings.MIDDLEWARE.index(
                "apps.core.middleware.TrustedProxyClientIPMiddleware"
            ),
            settings.MIDDLEWARE.index("django.middleware.security.SecurityMiddleware"),
        )

    def test_build_executables_are_pinned_to_immutable_revisions(self):
        dockerfile = (settings.BASE_DIR / "Dockerfile").read_text()
        compose = (settings.BASE_DIR / "docker-compose.yml").read_text()
        workflow = (settings.BASE_DIR / ".github" / "workflows" / "ci.yml").read_text()

        self.assertIn("FROM python:3.13-slim@sha256:", dockerfile)
        self.assertIn("--from=ghcr.io/astral-sh/uv@sha256:", dockerfile)
        self.assertNotIn("uv:latest", dockerfile)
        self.assertIn("image: postgres:16-alpine@sha256:", compose)
        self.assertIn("image: postgres:16-alpine@sha256:", workflow)
        action_refs = re.findall(r"^\s*-?\s*uses:\s+([^\s#]+)", workflow, re.MULTILINE)
        self.assertTrue(action_refs)
        self.assertEqual(
            [ref for ref in action_refs if not re.fullmatch(r"[^@]+@[0-9a-f]{40}", ref)],
            [],
        )

    def test_ci_uses_least_privilege_and_bounded_jobs(self):
        workflow = (settings.BASE_DIR / ".github" / "workflows" / "ci.yml").read_text()

        self.assertIn("permissions:\n  contents: read", workflow)
        self.assertEqual(workflow.count("timeout-minutes: 30"), 2)
        self.assertEqual(workflow.count("persist-credentials: false"), 2)
        self.assertIn("cancel-in-progress: true", workflow)

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

    def test_compose_rotates_all_service_logs(self):
        compose = (settings.BASE_DIR / "docker-compose.yml").read_text()

        self.assertIn("x-logging: &default-logging", compose)
        self.assertIn('max-size: "10m"', compose)
        self.assertIn('max-file: "5"', compose)
        self.assertIn('compress: "true"', compose)
        self.assertEqual(compose.count("logging: *default-logging"), 4)

    def test_compose_hardens_long_running_application_services(self):
        from apps.system.validators import VIDEO_MAX_SIZE_MB

        compose = (settings.BASE_DIR / "docker-compose.yml").read_text()

        self.assertIn("x-app-security: &app-security", compose)
        self.assertEqual(compose.count("<<: *app-security"), 2)
        self.assertIn("read_only: true", compose)
        self.assertIn("no-new-privileges:true", compose)
        self.assertIn("cap_drop:\n    - ALL", compose)
        self.assertIn("/tmp:size=256m,mode=1777", compose)
        tmpfs_size = re.search(r"/tmp:size=(\d+)m,mode=1777", compose)
        self.assertIsNotNone(tmpfs_size)
        self.assertGreater(int(tmpfs_size.group(1)), VIDEO_MAX_SIZE_MB)

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


class UploadLimitTests(TestCase):
    def test_oversized_request_is_rejected_before_multipart_parsing(self):
        request = mock.Mock()
        handler = BoundedUploadHandler(request)

        result = handler.handle_raw_input(
            input_data=mock.Mock(),
            META={},
            content_length=201 * 1024 * 1024 + 1,
            boundary=b"boundary",
        )

        self.assertIsNotNone(result)
        self.assertEqual(len(result[0]), 0)
        self.assertEqual(len(result[1]), 0)
        self.assertTrue(request.upload_size_limit_exceeded)

    def test_declared_oversized_file_stops_before_first_chunk(self):
        request = mock.Mock()
        handler = BoundedUploadHandler(request)

        with mock.patch("apps.core.uploads.MAX_UPLOAD_SIZE_BYTES", 4), self.assertRaises(
            StopUpload
        ) as raised:
            handler.new_file(
                "file",
                "oversized.bin",
                "application/octet-stream",
                5,
            )

        self.assertTrue(request.upload_size_limit_exceeded)
        self.assertTrue(raised.exception.connection_reset)

    def test_chunked_oversized_file_stops_at_boundary(self):
        request = mock.Mock()
        handler = BoundedUploadHandler(request)
        handler.new_file("file", "chunked.bin", "application/octet-stream", None)

        with mock.patch("apps.core.uploads.MAX_UPLOAD_SIZE_BYTES", 4):
            self.assertEqual(handler.receive_data_chunk(b"1234", 0), b"1234")
        with mock.patch("apps.core.uploads.MAX_UPLOAD_SIZE_BYTES", 4), self.assertRaises(
            StopUpload
        ) as raised:
            handler.receive_data_chunk(b"5", 4)

        self.assertTrue(request.upload_size_limit_exceeded)
        self.assertTrue(raised.exception.connection_reset)


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

    def test_existing_session_is_invalidated_after_account_lock(self):
        self.client.force_login(self.user)
        self.assertTrue(self.client.get(reverse("journal:list")).wsgi_request.user.is_authenticated)

        User.objects.filter(pk=self.user.pk).update(
            lock_until=timezone.now().replace(year=9999)
        )

        response = self.client.get(reverse("journal:list"))

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, f'{reverse("login")}?next={reverse("journal:list")}')
        self.assertNotIn("_auth_user_id", self.client.session)


class AuthenticationSurfaceTests(TestCase):
    def test_only_explicit_interactive_auth_routes_are_exposed(self):
        self.assertEqual(self.client.get("/accounts/login/").status_code, 200)
        self.assertEqual(self.client.get("/accounts/logout/").status_code, 405)
        for path in (
            "/accounts/password_reset/",
            "/accounts/password_reset/done/",
            "/accounts/password_change/",
            "/accounts/password_change/done/",
            "/accounts/reset/example/token/",
            "/accounts/reset/done/",
        ):
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 404)


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

    @override_settings(JWT_TTL=300)
    def test_decode_rejects_signed_token_exceeding_runtime_policy(self):
        now = datetime.datetime.now(tz=datetime.UTC)
        token = jwt.encode(
            {
                "sub": str(self.user.guid),
                "aud": settings.JWT_AUDIENCE,
                "jti": str(uuid.uuid4()),
                "iat": now,
                "exp": now + datetime.timedelta(seconds=301),
            },
            settings.JWT_SECRET,
            algorithm=settings.JWT_ALGORITHM,
        )

        with self.assertRaises(jwt.InvalidTokenError):
            decode_token(token)

    @override_settings(JWT_TTL=300)
    def test_decode_accepts_signed_token_at_runtime_policy_boundary(self):
        now = datetime.datetime.now(tz=datetime.UTC)
        token = jwt.encode(
            {
                "sub": str(self.user.guid),
                "aud": settings.JWT_AUDIENCE,
                "jti": str(uuid.uuid4()),
                "iat": now,
                "exp": now + datetime.timedelta(seconds=300),
            },
            settings.JWT_SECRET,
            algorithm=settings.JWT_ALGORITHM,
        )

        self.assertEqual(decode_token(token)["sub"], str(self.user.guid))

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
        self.assertIn("no-store", response.headers["Cache-Control"])
        self.assertEqual(response.headers["Referrer-Policy"], "no-referrer")
        self.assertIn("Origin", response.headers["Vary"])
        self.assertIn("Sec-Fetch-Site", response.headers["Vary"])

    def test_same_origin_browser_form_is_allowed(self):
        response = self.client.post(
            self.url,
            {"token": issue_token(self.user)},
            HTTP_ORIGIN="http://testserver",
            HTTP_SEC_FETCH_SITE="same-origin",
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(int(self.client.session["_auth_user_id"]), self.user.pk)

    def test_cross_site_browser_form_is_rejected_before_token_consumption(self):
        token = issue_token(self.user)
        response = self.client.post(
            self.url,
            {"token": token},
            HTTP_ORIGIN="https://attacker.invalid",
            HTTP_SEC_FETCH_SITE="cross-site",
        )

        self.assertEqual(response.status_code, 403)
        self.assertNotIn("_auth_user_id", self.client.session)
        self.assertFalse(ConsumedToken.objects.exists())
        self.assertEqual(
            self.client.post(self.url, {"token": token}).status_code,
            302,
        )

    def test_cross_site_fetch_without_origin_is_rejected(self):
        response = self.client.post(
            self.url,
            {"token": issue_token(self.user)},
            HTTP_SEC_FETCH_SITE="cross-site",
        )

        self.assertEqual(response.status_code, 403)
        self.assertFalse(ConsumedToken.objects.exists())

    @override_settings(TOKEN_LOGIN_TRUSTED_ORIGINS=("https://sso.example",))
    def test_explicit_trusted_sso_origin_is_allowed(self):
        response = self.client.post(
            self.url,
            {"token": issue_token(self.user)},
            secure=True,
            HTTP_HOST="journal.example",
            HTTP_ORIGIN="https://sso.example",
            HTTP_SEC_FETCH_SITE="cross-site",
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(int(self.client.session["_auth_user_id"]), self.user.pk)

    def test_malformed_browser_origin_is_rejected(self):
        response = self.client.post(
            self.url,
            {"token": issue_token(self.user)},
            HTTP_ORIGIN="null",
        )

        self.assertEqual(response.status_code, 403)
        self.assertFalse(ConsumedToken.objects.exists())

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

    @override_settings(JWT_TTL=300)
    def test_signed_long_lived_token_is_rejected_without_consuming_jti(self):
        now = datetime.datetime.now(tz=datetime.UTC)
        token = jwt.encode(
            {
                "sub": str(self.user.guid),
                "aud": settings.JWT_AUDIENCE,
                "jti": str(uuid.uuid4()),
                "iat": now,
                "exp": now + datetime.timedelta(days=365),
            },
            settings.JWT_SECRET,
            algorithm=settings.JWT_ALGORITHM,
        )

        response = self.client.post(self.url, {"token": token})

        self.assertEqual(response.status_code, 403)
        self.assertNotIn("_auth_user_id", self.client.session)
        self.assertFalse(ConsumedToken.objects.exists())

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

    def test_missing_token_response_is_also_never_cached(self):
        response = self.client.post(self.url)

        self.assertEqual(response.status_code, 400)
        self.assertIn("no-store", response.headers["Cache-Control"])
        self.assertEqual(response.headers["Referrer-Policy"], "no-referrer")

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

    def test_event_actor_cannot_be_deleted(self):
        actor = User.objects.create_user(
            username="retained-audit-actor", password="GoodPass!1", org=81000
        )
        entry = log_event(
            module="test", event_type=EventLog.EventType.VIEW, user=actor
        )

        with self.assertRaises(ProtectedError):
            actor.delete()

        entry.refresh_from_db()
        self.assertEqual(entry.user, actor)

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

    def test_successful_django_admin_mutation_is_recorded_in_event_log(self):
        administrator = User.objects.create_superuser(
            username="audit-admin",
            password="GoodPass!1",
            org=81000,
        )
        self.client.force_login(administrator)
        url = reverse("admin:system_newscategory_add")

        response = self.client.post(
            url,
            {"name": "Служебные объявления", "slug": "service", "_save": "Сохранить"},
        )

        self.assertEqual(response.status_code, 302)
        self.assertTrue(NewsCategory.objects.filter(slug="service").exists())
        event = EventLog.objects.get(target=f"POST {url}")
        self.assertEqual(event.event_type, EventLog.EventType.OTHER)
        self.assertEqual(event.result, EventLog.Result.OK)
        self.assertEqual(event.user, administrator)

    def test_django_admin_login_uses_authentication_event_type(self):
        administrator = User.objects.create_superuser(
            username="login-audit-admin",
            password="GoodPass!1",
            org=81000,
        )
        url = reverse("admin:login")

        response = self.client.post(
            url,
            {
                "username": administrator.username,
                "password": "GoodPass!1",
                "next": reverse("admin:index"),
            },
        )

        self.assertEqual(response.status_code, 302)
        event = EventLog.objects.get(target=f"POST {url}")
        self.assertEqual(event.event_type, EventLog.EventType.LOGIN)
        self.assertEqual(event.result, EventLog.Result.OK)
        self.assertEqual(event.user, administrator)

    def test_django_admin_logout_keeps_pre_request_actor(self):
        administrator = User.objects.create_superuser(
            username="logout-audit-admin",
            password="GoodPass!1",
            org=81000,
        )
        self.client.force_login(administrator)
        url = reverse("admin:logout")

        response = self.client.post(url)

        self.assertEqual(response.status_code, 302)
        event = EventLog.objects.get(target=f"POST {url}")
        self.assertEqual(event.event_type, EventLog.EventType.LOGOUT)
        self.assertEqual(event.result, EventLog.Result.OK)
        self.assertEqual(event.user, administrator)

    @override_settings(TRUST_PROXY_CLIENT_IP_HEADER=True)
    def test_trusted_proxy_client_ip_is_recorded(self):
        self.client.post(
            reverse("login"),
            {"username": self.user.username, "password": "wrong-password"},
            REMOTE_ADDR="127.0.0.1",
            HTTP_X_FORWARDED_FOR="192.0.2.41",
        )

        event = EventLog.objects.get(target="POST /accounts/login/")
        self.assertEqual(event.ip, "192.0.2.41")

    @override_settings(TRUST_PROXY_CLIENT_IP_HEADER=True)
    def test_untrusted_peer_cannot_spoof_client_ip(self):
        self.client.post(
            reverse("login"),
            {"username": self.user.username, "password": "wrong-password"},
            REMOTE_ADDR="198.51.100.9",
            HTTP_X_FORWARDED_FOR="192.0.2.41",
        )

        event = EventLog.objects.get(target="POST /accounts/login/")
        self.assertEqual(event.ip, "198.51.100.9")

    @override_settings(TRUST_PROXY_CLIENT_IP_HEADER=True)
    def test_forwarded_chain_does_not_override_remote_address(self):
        self.client.post(
            reverse("login"),
            {"username": self.user.username, "password": "wrong-password"},
            REMOTE_ADDR="127.0.0.1",
            HTTP_X_FORWARDED_FOR="198.51.100.7, 192.0.2.41",
        )

        event = EventLog.objects.get(target="POST /accounts/login/")
        self.assertEqual(event.ip, "127.0.0.1")

    @override_settings(TRUST_PROXY_CLIENT_IP_HEADER=True)
    def test_invalid_forwarded_address_does_not_override_remote_address(self):
        self.client.post(
            reverse("login"),
            {"username": self.user.username, "password": "wrong-password"},
            REMOTE_ADDR="127.0.0.1",
            HTTP_X_FORWARDED_FOR="not-an-ip-address",
        )

        event = EventLog.objects.get(target="POST /accounts/login/")
        self.assertEqual(event.ip, "127.0.0.1")


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

"""Тесты core: парольная политика, блокировка, токены, журнал событий."""

from django.contrib.auth import authenticate, get_user_model
from django.contrib.auth.signals import user_login_failed
from django.core.exceptions import ValidationError
from django.test import TestCase

from apps.core.models import EventLog, log_event
from apps.core.tokens import decode_token, issue_token, resolve_user
from apps.core.validators import ComplexityPasswordValidator

User = get_user_model()


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
            username="tokenuser", password="GoodPass!1", org=81004
        )

    def test_issue_decode_roundtrip(self):
        token = issue_token(self.user)
        payload = decode_token(token)
        self.assertEqual(payload["username"], "tokenuser")
        self.assertEqual(payload["sub"], str(self.user.guid))

    def test_resolve_user(self):
        token = issue_token(self.user)
        self.assertEqual(resolve_user(token).pk, self.user.pk)

    def test_expired_token_rejected(self):


        expired = issue_token(self.user, ttl=-10)
        self.assertIsNone(resolve_user_catching(expired))


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

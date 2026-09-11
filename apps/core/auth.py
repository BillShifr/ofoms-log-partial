"""Сквозная аутентификация v2.

- TFOMSAuthBackend: расширение ModelBackend с проверкой блокировки.
- Сигналы user_login_failed / user_logged_in: подсчёт попыток (лимит 10,
  ТЗ разд. 3.1) и журналирование в EventLog (ТЗ разд. 3.4).

Единая сквозная авторизация с временными токенами (external офис-системы)
реализуется отдельным модулем apps.core.tokens (PyJWT) — см. Этап 5.
"""

from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend
from django.contrib.auth.models import AnonymousUser
from django.contrib.auth.signals import user_logged_in, user_login_failed
from django.dispatch import receiver

from apps.core.models import EventLog, log_event

UserModel = get_user_model()


class TFOMSAuthBackend(ModelBackend):
    """ModelBackend + проверка блокировки учётной записи."""

    def authenticate(self, request, username=None, password=None, **kwargs):
        user = super().authenticate(request, username=username, password=password, **kwargs)
        if user is None:
            return None
        if user.is_locked:
            return None
        return user

    def get_user(self, user_id):
        """Не восстанавливает из сессии уже заблокированную учётную запись."""
        user = super().get_user(user_id)
        if user is None or user.is_locked:
            return None
        return user


def _client_ip(request):
    if request is None:
        return None
    return request.META.get("REMOTE_ADDR")


@receiver(user_login_failed)
def on_login_failed(sender, credentials, request=None, **kwargs):
    username = credentials.get("username", "")
    user = UserModel.objects.filter(username=username).first()
    if user is not None:
        user.record_failed_login()
        log_event(
            module="auth",
            event_type=EventLog.EventType.BLOCK
            if user.failed_attempts >= _max_failed()
            else EventLog.EventType.LOGIN_FAILED,
            user=user,
            target=f"login:{username}",
            ip=_client_ip(request),
        )


@receiver(user_logged_in)
def on_logged_in(sender, request, user, **kwargs):
    if getattr(user, "failed_attempts", 0) or getattr(user, "lock_until", None):
        user.reset_failed_logins()
    if user is not None and not isinstance(user, AnonymousUser) and hasattr(user, "pk"):
        log_event(
            module="auth",
            event_type=EventLog.EventType.LOGIN,
            user=user,
            target=f"login:{user.username}",
            ip=_client_ip(request),
        )


def _max_failed():
    from django.conf import settings

    return settings.SECURITY_MAX_FAILED_LOGIN_ATTEMPTS

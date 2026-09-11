"""AuditMiddleware: сквозное журналирование HTTP-запросов (ТЗ разд. 3.4, СЗИ).

Фиксирует вход, выход, критичные операции (POST с изменениями) и ошибки.
Не логирует статику и liveness/readiness-проверки.
"""

import contextlib
import ipaddress
import time

from django.conf import settings
from django.contrib.auth import SESSION_KEY, logout
from django.http import HttpResponse

from apps.core.models import EventLog, log_event

_IGNORED_PREFIXES = ("/static/", "/media/", "/healthz", "/readyz", "/favicon.ico")
_IGNORED_ADMIN_SEGMENTS = ("/admin/jsi18n",)
_LOGIN_PATHS = ("/accounts/login/", "/accounts/token-login/")


class TrustedProxyClientIPMiddleware:
    """Восстанавливает REMOTE_ADDR только из проверенного proxy-контракта."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if settings.TRUST_PROXY_CLIENT_IP_HEADER:
            forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR", "").strip()
            if forwarded_for and "," not in forwarded_for:
                with contextlib.suppress(ValueError):
                    request.META["REMOTE_ADDR"] = str(
                        ipaddress.ip_address(forwarded_for)
                    )
        return self.get_response(request)


class AccountStateSessionMiddleware:
    """Удаляет сессию, если её пользователь больше не может войти в систему."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if SESSION_KEY in request.session and not request.user.is_authenticated:
            logout(request)
        return self.get_response(request)


class ContentSecurityPolicyMiddleware:
    """Запрещает inline/external scripts на пользовательских экранах портала."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        response.headers.setdefault("Permissions-Policy", settings.PERMISSIONS_POLICY)
        if not request.path.startswith("/admin/"):
            response.headers.setdefault(
                "Content-Security-Policy", settings.CONTENT_SECURITY_POLICY
            )
        return response


class SensitiveResponseCacheMiddleware:
    """Запрещает хранение динамических ответов портала браузером и proxy."""

    _CACHE_CONTROL = "no-store, no-cache, max-age=0, private"

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        if not request.path.startswith(settings.STATIC_URL):
            response.headers["Cache-Control"] = self._CACHE_CONTROL
            response.headers["Pragma"] = "no-cache"
            response.headers["Expires"] = "0"
        return response


class AuditMiddleware:
    """Простая промежуточная защита: HTTP-аудит действий пользователя."""

    def __init__(self, get_response):
        self.get_response = get_response

    def _should_ignore(self, request) -> bool:
        path = request.path
        return any(path.startswith(p) for p in _IGNORED_PREFIXES) or any(
            path.startswith(s) for s in _IGNORED_ADMIN_SEGMENTS
        )

    def __call__(self, request):
        if self._should_ignore(request):
            return self.get_response(request)

        started_at = time.perf_counter()
        user_before = request.user if getattr(request, "user", None) else None
        response = self.get_response(request)
        user_after = request.user if getattr(request, "user", None) else None

        duration_ms = int((time.perf_counter() - started_at) * 1000)

        if isinstance(response, HttpResponse):
            status = response.status_code
        else:
            status = 200

        # Логируем вход/выход и все не-GET запросы (изменения данных)
        event_type = None
        actor = user_before
        if request.path in _LOGIN_PATHS and request.method == "POST":
            actor = user_after
            event_type = (
                EventLog.EventType.LOGIN
                if actor and actor.is_authenticated
                else EventLog.EventType.LOGIN_FAILED
            )
        elif request.path.startswith("/accounts/logout"):
            event_type = EventLog.EventType.LOGOUT
        elif status >= 500 or status >= 400:
            event_type = EventLog.EventType.OTHER

        if event_type is not None or (
            request.method not in ("GET", "HEAD") and not request.path.startswith("/admin/")
        ):
            if status in (401, 403):
                result = EventLog.Result.DENIED
            elif event_type == EventLog.EventType.LOGIN_FAILED or status >= 400:
                result = EventLog.Result.FAILED
            else:
                result = EventLog.Result.OK
            log_event(
                module="http",
                event_type=event_type or EventLog.EventType.OTHER,
                result=result,
                user=actor if actor and actor.is_authenticated else None,
                target=f"{request.method} {request.path}",
                ip=request.META.get("REMOTE_ADDR"),
                duration_ms=duration_ms,
            )

        return response

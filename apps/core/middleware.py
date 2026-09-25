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
_LOGIN_PATHS = ("/accounts/login/", "/accounts/token-login/", "/admin/login/")
_LOGOUT_PATHS = ("/accounts/logout/", "/admin/logout/")


class TrustedProxyClientIPMiddleware:
    """Принимает forwarded headers только от настроенного proxy peer."""

    def __init__(self, get_response):
        self.get_response = get_response
        self.trusted_networks = tuple(
            ipaddress.ip_network(network)
            for network in settings.TRUSTED_PROXY_IPS
        )

    def _peer_is_trusted(self, request):
        try:
            peer = ipaddress.ip_address(request.META.get("REMOTE_ADDR", ""))
        except ValueError:
            return False
        return any(peer in network for network in self.trusted_networks)

    def __call__(self, request):
        peer_is_trusted = self._peer_is_trusted(request)
        if not settings.TRUST_PROXY_SSL_HEADER or not peer_is_trusted:
            request.META.pop("HTTP_X_FORWARDED_PROTO", None)

        if settings.TRUST_PROXY_CLIENT_IP_HEADER and peer_is_trusted:
            forwarded_for = request.META.pop("HTTP_X_FORWARDED_FOR", "").strip()
            if forwarded_for and "," not in forwarded_for:
                with contextlib.suppress(ValueError):
                    request.META["REMOTE_ADDR"] = str(
                        ipaddress.ip_address(forwarded_for)
                    )
        else:
            request.META.pop("HTTP_X_FORWARDED_FOR", None)
        return self.get_response(request)


class AccountStateSessionMiddleware:
    """Удаляет сессию, если её пользователь больше не может войти в систему."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if SESSION_KEY in request.session and not request.user.is_authenticated:
            logout(request)
        return self.get_response(request)


class UploadLimitResponseMiddleware:
    """Не запускает view после остановки чрезмерного multipart upload."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.method == "POST" and request.content_type.startswith("multipart/"):
            _ = request.POST
        if getattr(request, "upload_size_limit_exceeded", False):
            return HttpResponse("Файл превышает допустимый размер.", status=413)
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

        # аудит включает вход выход и запросы изменения данных
        event_type = None
        actor = user_before
        if request.path in _LOGIN_PATHS and request.method == "POST":
            actor = user_after
            event_type = (
                EventLog.EventType.LOGIN
                if actor and actor.is_authenticated
                else EventLog.EventType.LOGIN_FAILED
            )
        elif request.path in _LOGOUT_PATHS and request.method == "POST":
            event_type = EventLog.EventType.LOGOUT
        elif status >= 500 or status >= 400:
            event_type = EventLog.EventType.OTHER

        if event_type is not None or request.method not in ("GET", "HEAD"):
            if status in (401, 403):
                result = EventLog.Result.DENIED
            elif event_type == EventLog.EventType.LOGIN_FAILED or status >= 400:
                result = EventLog.Result.FAILED
            else:
                result = EventLog.Result.OK
            canonical = getattr(request, "_canonical_auth_event", None)
            if canonical is not None and canonical.event_type != EventLog.EventType.BLOCK:
                canonical.module = "http"
                canonical.event_type = event_type or canonical.event_type
                canonical.user = actor if actor and actor.is_authenticated else None
                canonical.target = f"{request.method} {request.path}"
                canonical.ip = request.META.get("REMOTE_ADDR")
                canonical = log_event(
                    module="http",
                    event_type=canonical.event_type,
                    obj=canonical,
                    result=result,
                    duration_ms=duration_ms,
                )
                canonical.save(
                    update_fields=["module", "event_type", "user", "target", "ip"]
                )
            else:
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

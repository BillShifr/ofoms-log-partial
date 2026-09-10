"""AuditMiddleware: сквозное журналирование HTTP-запросов (ТЗ разд. 3.4, СЗИ).

Фиксирует вход, выход, критичные операции (POST с изменениями) и ошибки.
Не логирует статику и healthz-проверки.
"""

import time

from django.http import HttpResponse

from apps.core.models import EventLog

_IGNORED_PREFIXES = ("/static/", "/media/", "/healthz", "/favicon.ico")
_IGNORED_ADMIN_SEGMENTS = ("/admin/jsi18n",)


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
        user = request.user if getattr(request, "user", None) else None
        response = self.get_response(request)

        duration_ms = int((time.perf_counter() - started_at) * 1000)

        if isinstance(response, HttpResponse):
            status = response.status_code
        else:
            status = 200

        # Логируем вход/выход и все не-GET запросы (изменения данных)
        event_type = None
        if request.path.startswith("/accounts/login") and request.method == "POST":
            event_type = (
                EventLog.EventType.LOGIN
                if user and user.is_authenticated
                else EventLog.EventType.LOGIN_FAILED
            )
        elif request.path.startswith("/accounts/logout"):
            event_type = EventLog.EventType.LOGOUT
        elif status >= 500 or status >= 400:
            event_type = EventLog.EventType.OTHER

        if event_type is not None or (
            request.method not in ("GET", "HEAD") and not request.path.startswith("/admin/")
        ):
            EventLog.objects.create(
                module="http",
                event_type=event_type or EventLog.EventType.OTHER,
                result=(
                    EventLog.Result.OK
                    if status < 400
                    else EventLog.Result.FAILED
                    if status < 500
                    else EventLog.Result.FAILED
                ),
                user=user if user and user.is_authenticated else None,
                target=f"{request.method} {request.path}",
                ip=request.META.get("REMOTE_ADDR"),
                duration_ms=duration_ms,
            )

        return response

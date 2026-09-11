"""Маршрутизация v2: админка + бэкенд-API журнала (каркас).

На Этапе 2 к этому дереву добавится кастомный экран журнала (apps.journal.urls).
"""

from django.contrib import admin
from django.db import DatabaseError, connections
from django.http import HttpResponse
from django.urls import include, path
from django.views.decorators.http import require_GET
from django.views.generic import RedirectView

admin.site.site_header = "Единый электронный журнал обращений граждан — администрирование"
admin.site.site_title = "ЭЖ обращений граждан — ТФОМС ХМАО — Югры"
admin.site.index_title = "Панель управления"


def _health_response(body, *, status=200):
    response = HttpResponse(body, status=status, content_type="text/plain")
    response.headers["Cache-Control"] = "no-store"
    return response


@require_GET
def healthz(_request):
    """Liveness: процесс Django отвечает и способен сформировать HTTP response."""
    return _health_response("ok")


@require_GET
def readyz(_request):
    """Readiness: приложение обслуживает запросы только при доступной основной БД."""
    try:
        with connections["default"].cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
    except DatabaseError:
        return _health_response("unavailable", status=503)
    return _health_response("ready")


urlpatterns = [
    path("", RedirectView.as_view(pattern_name="journal:list", permanent=False), name="index"),
    path("healthz", healthz, name="healthz"),
    path("readyz", readyz, name="readyz"),
    path("admin/", admin.site.urls),
    path("accounts/", include("apps.core.urls")),
    path("accounts/", include("django.contrib.auth.urls")),
    path("journal/", include("apps.journal.urls")),
    path("exchange/", include("apps.exchange.urls")),
    path("reports/", include("apps.reports.urls")),
    path("system/", include("apps.system.urls")),
]

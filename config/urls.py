"""Маршрутизация v2: админка + бэкенд-API журнала (каркас).

На Этапе 2 к этому дереву добавится кастомный экран журнала (apps.journal.urls).
"""

from django.contrib import admin
from django.http import HttpResponse
from django.urls import include, path
from django.views.generic import RedirectView

admin.site.site_header = "Единый электронный журнал обращений граждан — администрирование"
admin.site.site_title = "ЭЖ обращений граждан — ТФОМС ХМАО — Югры"
admin.site.index_title = "Панель управления"


def healthz(_request):
    """Точка доступности для Docker healthcheck."""
    return HttpResponse("ok", content_type="text/plain")


urlpatterns = [
    path("", RedirectView.as_view(pattern_name="journal:list", permanent=False), name="index"),
    path("healthz", healthz, name="healthz"),
    path("admin/", admin.site.urls),
    path("accounts/", include("apps.core.urls")),
    path("accounts/", include("django.contrib.auth.urls")),
    path("journal/", include("apps.journal.urls")),
    path("exchange/", include("apps.exchange.urls")),
    path("reports/", include("apps.reports.urls")),
    path("system/", include("apps.system.urls")),
]

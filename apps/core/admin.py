"""Администрирование журнала событий (ТЗ разд. 3.4)."""

from django.contrib import admin
from django.contrib.admin import DateFieldListFilter, SimpleListFilter
from rangefilter.filters import DateRangeFilter

from apps.core.admin_utils import OrganizationScopedAdminMixin, ReadOnlyAdminMixin
from apps.core.models import EventLog


class EventUserFilter(SimpleListFilter):
    title = "Инициатор"
    parameter_name = "user"

    def lookups(self, request, model_admin):
        qs = model_admin.get_queryset(request).exclude(user=None)
        seen = set()
        out = []
        for e in qs.select_related("user")[:500]:
            if e.user_id in seen:
                continue
            seen.add(e.user_id)
            out.append((str(e.user_id), str(e.user)))
        return out

    def queryset(self, request, queryset):
        if self.value():
            return queryset.filter(user_id=self.value())
        return queryset


@admin.register(EventLog)
class EventLogAdmin(
    OrganizationScopedAdminMixin, ReadOnlyAdminMixin, admin.ModelAdmin
):
    organization_lookup = "user__org"
    list_display = (
        "id",
        "started_at",
        "module",
        "event_type",
        "result",
        "user",
        "ip",
        "target",
        "duration_ms",
    )
    list_filter = (
        "module",
        "event_type",
        "result",
        ("started_at", DateRangeFilter),
        ("started_at", DateFieldListFilter),
        EventUserFilter,
    )
    search_fields = ("target", "detail", "ip")
    date_hierarchy = "started_at"

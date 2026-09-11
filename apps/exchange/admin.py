from django.contrib import admin

from apps.core.admin_utils import ImmutableAdminMixin
from apps.exchange.models import ImportLog


@admin.register(ImportLog)
class ImportLogAdmin(ImmutableAdminMixin, admin.ModelAdmin):
    list_display = ("filename", "org", "kind", "status", "rows", "created_at")
    list_filter = ("org", "kind", "status")
    search_fields = ("filename",)

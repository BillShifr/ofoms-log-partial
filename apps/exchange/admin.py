from django.contrib import admin

from apps.exchange.models import ImportLog


@admin.register(ImportLog)
class ImportLogAdmin(admin.ModelAdmin):
    list_display = ("filename", "org", "kind", "status", "rows", "created_at")
    list_filter = ("org", "kind", "status")
    search_fields = ("filename",)
    readonly_fields = ("created_at",)

    def has_add_permission(self, request):
        # Протоколы создаются только автоматически при обработке файлов
        return False

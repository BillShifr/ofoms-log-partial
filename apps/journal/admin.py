"""Администрирование журнала обращений (перенос из v1 + экспорт/импорт)."""

from django.contrib import admin
from django.contrib.admin import SimpleListFilter
from import_export.admin import ExportMixin
from rangefilter.filters import DateRangeFilterBuilder

from apps.core.admin_utils import (
    AuditedAdminMixin,
    OrganizationScopedAdminMixin,
    ReadOnlyAdminMixin,
)
from apps.core.exports import excel_safe_value
from apps.core.models import EventLog, log_event
from apps.employee.models import ORGS
from apps.journal.models import (
    Irp,
    IrpAnswer,
    IrpFile,
    IrpHistory,
    IrpTheme,
    XmlFiles,
)


class ScopedEmployeeFilter(SimpleListFilter):
    """Фильтр исполнителя без раскрытия сотрудников вне admin tenant scope."""

    title = "Принял"
    parameter_name = "employee_one"

    def lookups(self, request, model_admin):
        rows = (
            model_admin.get_queryset(request)
            .order_by("employee_one_id")
            .values_list(
                "employee_one_id",
                "employee_one__last_name",
                "employee_one__first_name",
                "employee_one__username",
            )
            .distinct()
        )
        return [
            (
                str(employee_id),
                " ".join(part for part in (last_name, first_name) if part)
                or username,
            )
            for employee_id, last_name, first_name, username in rows
        ]

    def queryset(self, request, queryset):
        value = self.value()
        if value:
            if not value.isascii() or not value.isdecimal() or int(value) < 1:
                return queryset.none()
            return queryset.filter(employee_one_id=int(value))
        return queryset


@admin.register(Irp)
class IrpAdmin(
    OrganizationScopedAdminMixin, ReadOnlyAdminMixin, ExportMixin, admin.ModelAdmin
):
    """Обращения: списком с фильтрами, карточка с полным набором реквизитов."""

    model = Irp

    class Media:
        js = ("/static/js/populate.js",)

    readonly_fields = ("input_file",)
    list_display = (
        "id",
        "org_name",
        "date_create",
        "irp_type",
        "theme__code_name",
        "z_f",
        "employee_one",
        "result",
        "date_close",
    )
    ordering = ("-date_create", "-id")

    def get_data_for_export(self, request, queryset, **kwargs):
        """Нейтрализует формулы во всех строковых ячейках admin-export."""
        dataset = super().get_data_for_export(request, queryset, **kwargs)
        for index, row in enumerate(dataset):
            dataset[index] = tuple(excel_safe_value(value) for value in row)
        return dataset

    def _do_file_export(self, file_format, request, queryset, export_form=None):
        """Фиксирует фактическую подготовку выгрузки до передачи ответа."""
        response = super()._do_file_export(
            file_format, request, queryset, export_form=export_form
        )
        log_event(
            module="journal",
            event_type=EventLog.EventType.EXPORT,
            user=request.user,
            target=f"admin:irp:export:{file_format.get_extension()}",
            ip=request.META.get("REMOTE_ADDR"),
        )
        return response

    fieldsets = [
        (
            "Обращение",
            {
                "fields": (
                    ("irp_type", "date_create", "time_create"),
                    ("way", "way_n", "how"),
                    ("zh_d", "theme"),
                    "theme_comment",
                    "text",
                    ("data_plan", "date_close", "result"),
                )
            },
        ),
        (
            "Обратившийся",
            {
                "fields": (
                    ("z_f", "z_i", "z_o"),
                    ("adr", "phone", "e_mail"),
                    ("z_dr", "z_enp", "z_smo"),
                    ("z_doctype", "z_docser", "z_docnum"),
                )
            },
        ),
        (
            "Застрахованный",
            {
                "fields": (
                    ("in_f", "in_i", "in_o"),
                    ("in_dr", "in_enp", "in_smo"),
                    ("in_doctype", "in_docser", "in_docnum"),
                )
            },
        ),
        ("Ответственный за рассмотрение", {"fields": (("otv_t",), ("otv_kon",))}),
        (
            "Исполнитель",
            {
                "fields": (
                    ("employee_one", "line_one"),
                    ("employee_it", "line_it"),
                )
            },
        ),
        (
            "Дополнительная информация",
            {"fields": (("n_irp", "tf_id"), "input_file")},
        ),
        (
            "Переадресация",
            {"fields": (("pr_out", "date_cross"), "time_cross")},
        ),
    ]

    list_filter = (
        "employee_one__org",
        "irp_type",
        "how",
        ("date_create", DateRangeFilterBuilder()),
        ScopedEmployeeFilter,
    )
    search_fields = ("^z_f", "in_f")

    organization_lookup = "employee_one__org"

    def org_name(self, obj):
        for code, name in ORGS:
            if code == obj.employee_one.org:
                return name
        return "---"

    org_name.short_description = "Организация"
    org_name.admin_order_field = "employee_one__org"


@admin.register(IrpTheme)
class IrpThemeAdmin(AuditedAdminMixin, admin.ModelAdmin):
    model = IrpTheme
    audit_module = "journal"
    readonly_fields = ("version",)
    list_display = ("code_name", "title", "version")
    list_filter = ("version",)
    search_fields = ("code_name", "title")


@admin.register(XmlFiles)
class XmlFilesAdmin(
    OrganizationScopedAdminMixin, ReadOnlyAdminMixin, admin.ModelAdmin
):
    organization_lookup = "smo"
    list_display = ("filename", "smo", "data", "version", "year", "month", "day")
    list_filter = ("smo", "year")


@admin.register(IrpHistory)
class IrpHistoryAdmin(
    OrganizationScopedAdminMixin, ReadOnlyAdminMixin, admin.ModelAdmin
):
    organization_lookup = "irp__employee_one__org"
    list_display = ("irp", "user", "changed_at")
    list_filter = ("changed_at",)


@admin.register(IrpAnswer)
class IrpAnswerAdmin(
    OrganizationScopedAdminMixin, ReadOnlyAdminMixin, admin.ModelAdmin
):
    organization_lookup = "irp__employee_one__org"
    list_display = ("irp", "user", "is_preliminary", "created_at")
    list_filter = ("is_preliminary",)
    search_fields = ("irp__n_irp", "text")


@admin.register(IrpFile)
class IrpFileAdmin(
    OrganizationScopedAdminMixin, ReadOnlyAdminMixin, admin.ModelAdmin
):
    organization_lookup = "irp__employee_one__org"
    list_display = ("id", "irp", "answer", "uploader", "created_at")

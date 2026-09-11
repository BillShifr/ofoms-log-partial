"""Администрирование журнала обращений (перенос из v1 + экспорт/импорт)."""

from django.contrib import admin
from django_admin_listfilter_dropdown.filters import RelatedDropdownFilter
from import_export.admin import ExportMixin
from rangefilter.filters import DateRangeFilterBuilder

from apps.core.admin_utils import ReadOnlyAdminMixin
from apps.employee.models import ORGS, TFOMS
from apps.journal.models import (
    Irp,
    IrpAnswer,
    IrpFile,
    IrpHistory,
    IrpTheme,
    XmlFiles,
)


@admin.register(Irp)
class IrpAdmin(ReadOnlyAdminMixin, ExportMixin, admin.ModelAdmin):
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
        ("employee_one", RelatedDropdownFilter),
    )
    search_fields = ("^z_f", "in_f")

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        org = request.user.org
        if org != TFOMS:
            qs = qs.filter(employee_one__org=org)
        return qs

    def org_name(self, obj):
        for code, name in ORGS:
            if code == obj.employee_one.org:
                return name
        return "---"

    org_name.short_description = "Организация"
    org_name.admin_order_field = "employee_one__org"


@admin.register(IrpTheme)
class IrpThemeAdmin(admin.ModelAdmin):
    model = IrpTheme
    readonly_fields = ("version",)
    list_display = ("code_name", "title", "version")
    list_filter = ("version",)
    search_fields = ("code_name", "title")


@admin.register(XmlFiles)
class XmlFilesAdmin(ReadOnlyAdminMixin, admin.ModelAdmin):
    list_display = ("filename", "smo", "data", "version", "year", "month", "day")
    list_filter = ("smo", "year")


@admin.register(IrpHistory)
class IrpHistoryAdmin(ReadOnlyAdminMixin, admin.ModelAdmin):
    list_display = ("irp", "user", "changed_at")
    list_filter = ("changed_at",)


@admin.register(IrpAnswer)
class IrpAnswerAdmin(ReadOnlyAdminMixin, admin.ModelAdmin):
    list_display = ("irp", "user", "is_preliminary", "created_at")
    list_filter = ("is_preliminary",)
    search_fields = ("irp__n_irp", "text")


@admin.register(IrpFile)
class IrpFileAdmin(ReadOnlyAdminMixin, admin.ModelAdmin):
    list_display = ("id", "irp", "answer", "uploader", "created_at")

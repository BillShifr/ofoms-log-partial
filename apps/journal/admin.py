"""Администрирование журнала обращений (перенос из v1 + экспорт/импорт)."""

import datetime
import uuid

from django.contrib import admin
from django_admin_listfilter_dropdown.filters import RelatedDropdownFilter
from import_export.admin import ExportMixin
from rangefilter.filters import DateRangeFilterBuilder

from apps.employee.models import ORGS, TFOMS, Employee
from apps.journal.models import (
    Irp,
    IrpAnswer,
    IrpFile,
    IrpHistory,
    IrpTheme,
    XmlFiles,
)


@admin.register(Irp)
class IrpAdmin(ExportMixin, admin.ModelAdmin):
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

    def formfield_for_choice_field(self, db_field, request, **kwargs):
        if db_field.name == "otv_t":
            if request.user.org == TFOMS:
                kwargs["choices"] = ((1, "ТФОМС"),)
            else:
                kwargs["choices"] = ((2, "СМО"),)
        if db_field.name == "otv_kon":
            kwargs["choices"] = (o for o in ORGS if o[0] == request.user.org)
        return super().formfield_for_choice_field(db_field, request, **kwargs)

    def get_readonly_fields(self, request, obj=None):
        if obj:
            return self.readonly_fields + (
                "employee_one",
                "n_irp",
                "otv_kon",
                "otv_t",
                "tf_id",
            )
        return self.readonly_fields

    def get_form(self, request, obj=None, **kwargs):
        form = super().get_form(request, obj, **kwargs)
        if not obj:
            form.base_fields["employee_it"].queryset = Employee.objects.filter(
                org=request.user.org
            )
            form.base_fields["employee_one"].queryset = Employee.objects.filter(
                org=request.user.org
            )
            form.base_fields["employee_one"].initial = Employee.objects.filter(
                pk=request.user.pk
            ).first()
            form.base_fields["n_irp"].initial = str(uuid.uuid4())
            form.base_fields["n_irp"].widget.attrs["readonly"] = True
            form.base_fields["date_create"].initial = datetime.date.today()
            form.base_fields["time_create"].initial = datetime.datetime.now()
            form.base_fields["data_plan"].initial = (
                datetime.date.today() + datetime.timedelta(days=30)
            )
            form.base_fields["theme"].queryset = IrpTheme.objects.filter(version=3)
        return form

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
class XmlFilesAdmin(admin.ModelAdmin):
    list_display = ("filename", "smo", "data", "version", "year", "month", "day")
    list_filter = ("smo", "year")


admin.site.register(IrpHistory)


@admin.register(IrpAnswer)
class IrpAnswerAdmin(admin.ModelAdmin):
    list_display = ("irp", "user", "is_preliminary", "created_at")
    list_filter = ("is_preliminary",)
    search_fields = ("irp__n_irp", "text")


admin.site.register(IrpFile)

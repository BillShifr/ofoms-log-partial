"""Администрирование сотрудников (пользователей) — перенос из v1."""

from apps.core.models import EventLog, log_event
from apps.core.roles import GROUP_ROLE_MAP, ROLE_GROUP_MAP, SMO_ROLES, TFOMS_ROLES
from apps.employee.models import TFOMS, Employee, GroupProxy
from django.contrib import admin
from django.contrib.auth.admin import GroupAdmin, UserAdmin
from django.contrib.auth.forms import UserChangeForm, UserCreationForm
from django.contrib.auth.models import Group
from django.core.exceptions import ValidationError
from django.db import transaction


class EmployeeChangeForm(UserChangeForm):
    class Meta(UserChangeForm.Meta):
        model = Employee

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["groups"].queryset = Group.objects.filter(
            name__in=ROLE_GROUP_MAP.values()
        ).order_by("name")

    def clean(self):
        cleaned = super().clean()
        groups = cleaned.get("groups")
        org = cleaned.get("org")
        if not groups or org is None:
            return cleaned
        allowed_codes = TFOMS_ROLES if org == TFOMS else SMO_ROLES
        invalid = [
            group.name
            for group in groups
            if GROUP_ROLE_MAP.get(group.name) not in allowed_codes
        ]
        if invalid:
            self.add_error(
                "groups",
                ValidationError(
                "Роли не соответствуют выбранной организации: " + ", ".join(invalid)
                ),
            )
        return cleaned


class EmployeeCreationForm(UserCreationForm):
    class Meta(UserCreationForm.Meta):
        model = Employee
        fields = UserCreationForm.Meta.fields + ("org",)


@admin.action(description="Разблокировать доступ (сбросить счётчик попыток)")
def unlock_accounts(modeladmin, request, queryset):
    n = 0
    with transaction.atomic():
        employees = Employee.objects.select_for_update().filter(
            pk__in=queryset.values_list("pk", flat=True)
        )
        for emp in employees:
            if emp.lock_until or emp.failed_attempts:
                emp.reset_failed_logins()
                log_event(
                    module="employee",
                    event_type=EventLog.EventType.UNBLOCK,
                    user=request.user,
                    target=f"employee:{emp.pk}:{emp.username}",
                    ip=request.META.get("REMOTE_ADDR"),
                )
                n += 1
    modeladmin.message_user(request, f"Разблокировано учётных записей: {n}")


@admin.register(Employee)
class EmployeeAdmin(UserAdmin):
    model = Employee
    form = EmployeeChangeForm
    add_form = EmployeeCreationForm
    actions = [unlock_accounts]

    list_display = ("full_name", "org", "username", "is_staff", "is_locked")
    list_filter = ("org", "is_staff", "is_active") + UserAdmin.list_filter
    search_fields = ("username", "last_name", "first_name", "job_title")
    fieldsets = UserAdmin.fieldsets + (
        ("Профиль", {"fields": ("job_title", "org", "guid", "failed_attempts", "lock_until")}),
    )
    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": ("username", "password1", "password2", "org"),
            },
        ),
    )
    readonly_fields = ("guid", "failed_attempts", "lock_until")

    def save_model(self, request, obj, form, change):
        obj._admin_audit_event_type = (
            EventLog.EventType.UPDATE if change else EventLog.EventType.CREATE
        )
        super().save_model(request, obj, form, change)

    def save_related(self, request, form, formsets, change):
        """Фиксирует поля и M2M-роли внутри транзакции change form Admin."""
        super().save_related(request, form, formsets, change)
        obj = form.instance
        event_type = getattr(
            obj,
            "_admin_audit_event_type",
            EventLog.EventType.UPDATE if change else EventLog.EventType.CREATE,
        )
        log_event(
            module="employee",
            event_type=event_type,
            user=request.user,
            target=f"admin:employee:{obj.pk}:{event_type}",
            ip=request.META.get("REMOTE_ADDR"),
        )
        if hasattr(obj, "_admin_audit_event_type"):
            del obj._admin_audit_event_type

    def get_readonly_fields(self, request, obj=None):
        fields = super().get_readonly_fields(request, obj)
        if obj is not None and obj.pk == request.user.pk:
            return (
                *fields,
                "is_active",
                "is_staff",
                "is_superuser",
                "groups",
                "user_permissions",
            )
        return fields

    def has_delete_permission(self, request, obj=None):
        """Учётные записи деактивируются, но не удаляются из audit trail."""
        return False

    def is_locked(self, obj):
        return obj.is_locked

    is_locked.boolean = True
    is_locked.short_description = "Заблокирован"


class RoleGroupAdmin(GroupAdmin):
    """Показывает только канонические роли и не позволяет менять их идентичность."""

    readonly_fields = ("name",)

    def get_queryset(self, request):
        return super().get_queryset(request).filter(name__in=ROLE_GROUP_MAP.values())

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return bool(request.user.is_superuser)

    def has_delete_permission(self, request, obj=None):
        return False

    def save_related(self, request, form, formsets, change):
        """Фиксирует изменение permission-набора внутри admin-транзакции."""
        super().save_related(request, form, formsets, change)
        role = form.instance
        log_event(
            module="employee",
            event_type=EventLog.EventType.UPDATE,
            user=request.user,
            target=f"admin:role:{role.pk}:permissions",
            ip=request.META.get("REMOTE_ADDR"),
        )


admin.site.unregister(Group)
admin.site.register(GroupProxy, RoleGroupAdmin)

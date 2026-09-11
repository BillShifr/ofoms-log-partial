"""Администрирование сотрудников (пользователей) — перенос из v1."""

from apps.core.models import EventLog
from apps.core.roles import GROUP_ROLE_MAP, ROLE_GROUP_MAP, SMO_ROLES, TFOMS_ROLES
from apps.employee.models import TFOMS, Employee, GroupProxy
from django.contrib import admin
from django.contrib.auth.admin import GroupAdmin, UserAdmin
from django.contrib.auth.forms import UserChangeForm, UserCreationForm
from django.contrib.auth.models import Group
from django.core.exceptions import ValidationError


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
    for emp in queryset:
        if emp.lock_until or emp.failed_attempts:
            emp.reset_failed_logins()
            EventLog.objects.create(
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


admin.site.unregister(Group)
admin.site.register(GroupProxy, RoleGroupAdmin)

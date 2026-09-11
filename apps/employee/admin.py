"""Администрирование сотрудников (пользователей) — перенос из v1."""

from apps.core.models import EventLog
from apps.employee.models import Employee, GroupProxy
from django.contrib import admin
from django.contrib.auth.admin import GroupAdmin, UserAdmin
from django.contrib.auth.forms import UserChangeForm, UserCreationForm
from django.contrib.auth.models import Group


class EmployeeChangeForm(UserChangeForm):
    class Meta(UserChangeForm.Meta):
        model = Employee


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

    def has_delete_permission(self, request, obj=None):
        """Учётные записи деактивируются, но не удаляются из audit trail."""
        return False

    def is_locked(self, obj):
        return obj.is_locked

    is_locked.boolean = True
    is_locked.short_description = "Заблокирован"


admin.site.unregister(Group)
admin.site.register(GroupProxy, GroupAdmin)

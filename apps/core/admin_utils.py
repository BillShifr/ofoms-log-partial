"""Общие ограничения для неизменяемых служебных записей в Django Admin."""

from django.db import transaction

from apps.core.models import EventLog, log_event


class OrganizationScopedAdminMixin:
    """Ограничивает admin queryset организацией для любого non-superuser."""

    organization_lookup = "org"

    def get_queryset(self, request):
        queryset = super().get_queryset(request)
        user = request.user
        from apps.employee.models import TFOMS

        if user.is_superuser or user.org == TFOMS:
            return queryset
        return queryset.filter(**{self.organization_lookup: user.org})


class ParticipantScopedAdminMixin:
    """Ограничивает admin queryset диалогами текущего участника."""

    participant_lookup = "participants"

    def get_queryset(self, request):
        return (
            super()
            .get_queryset(request)
            .filter(**{self.participant_lookup: request.user})
            .distinct()
        )


class AuditedAdminMixin:
    """Связывает CRUD справочника с предметным событием в admin-транзакции."""

    audit_module = "admin"

    def _audit_target(self, obj, action):
        return f"admin:{obj._meta.label_lower}:{obj.pk}:{action}"

    def _log_admin_change(self, request, obj, event_type, action):
        log_event(
            module=self.audit_module,
            event_type=event_type,
            user=request.user,
            target=self._audit_target(obj, action),
            ip=request.META.get("REMOTE_ADDR"),
        )

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        event_type = EventLog.EventType.UPDATE if change else EventLog.EventType.CREATE
        self._log_admin_change(request, obj, event_type, event_type)

    def delete_model(self, request, obj):
        target = self._audit_target(obj, EventLog.EventType.DELETE)
        super().delete_model(request, obj)
        log_event(
            module=self.audit_module,
            event_type=EventLog.EventType.DELETE,
            user=request.user,
            target=target,
            ip=request.META.get("REMOTE_ADDR"),
        )

    def delete_queryset(self, request, queryset):
        with transaction.atomic():
            targets = [
                self._audit_target(obj, EventLog.EventType.DELETE) for obj in queryset
            ]
            super().delete_queryset(request, queryset)
            for target in targets:
                log_event(
                    module=self.audit_module,
                    event_type=EventLog.EventType.DELETE,
                    user=request.user,
                    target=target,
                    ip=request.META.get("REMOTE_ADDR"),
                )


class ReadOnlyAdminMixin:
    """Оставляет защищённые модели доступными в Admin только для просмотра."""

    def get_readonly_fields(self, request, obj=None):
        return tuple(field.name for field in self.model._meta.fields)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

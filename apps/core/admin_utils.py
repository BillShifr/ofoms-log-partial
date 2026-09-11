"""Общие ограничения для неизменяемых служебных записей в Django Admin."""


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

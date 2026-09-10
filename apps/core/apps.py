"""Приложение core: сквозная безопасность и аудит (ТЗ разд. 3.1, ФСТЭК-2)."""

from django.apps import AppConfig


class CoreConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.core"
    verbose_name = "Ядро системы"

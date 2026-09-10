"""Настройки разработки (локальный запуск).

Django «development»-окружение: DEBUG=True, локальная БД, SQL-лог.
Используется по умолчанию в pytest и manage.py (dev).
"""

from .base import *  # noqa: F403

DEBUG = True

ALLOWED_HOSTS = ["*"]

# Локальная база по умолчанию
DATABASES["default"]["NAME"] = "ejournal"  # noqa: F405
DATABASES["default"]["USER"] = "ejournal"  # noqa: F405
DATABASES["default"]["PASSWORD"] = "ejournal"  # noqa: F405
DATABASES["default"]["HOST"] = "localhost"  # noqa: F405

# Email: вывод в консоль
EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"

# В dev/test не собираем manifest — отдаём статику как есть (быстрый запуск)
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {
        "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"
    },
}

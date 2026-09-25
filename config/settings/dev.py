"""Настройки разработки (локальный запуск).

Django «development»-окружение: DEBUG=True, локальная БД, SQL-лог.
Используется по умолчанию в pytest и manage.py (dev).
"""

from .base import *  # noqa: F403

DEBUG = True

ALLOWED_HOSTS = ["*"]

# локальная база
DATABASES["default"]["NAME"] = "ejournal"  # noqa: F405
DATABASES["default"]["USER"] = "ejournal"  # noqa: F405
DATABASES["default"]["PASSWORD"] = "ejournal"  # noqa: F405
DATABASES["default"]["HOST"] = "localhost"  # noqa: F405

# email выводится в консоль
EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"

# статика в dev и test отдается без manifest
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {
        "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"
    },
}

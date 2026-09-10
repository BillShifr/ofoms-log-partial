"""Настройки боевого окружения (контейнер).

Включаются через DJANGO_SETTINGS_MODULE=config.settings.prod
(см. docker-compose / systemd unit). Все секреты — из переменных окружения.
"""

import os

from .base import *  # noqa: F403

DEBUG = False

SECURE_SSL_REDIRECT = os.getenv("SECURE_SSL_REDIRECT", "False").lower() in (
    "1",
    "true",
    "yes",
)
SESSION_COOKIE_SECURE = os.getenv("SESSION_COOKIE_SECURE", "False").lower() in (
    "1",
    "true",
    "yes",
)
CSRF_COOKIE_SECURE = SESSION_COOKIE_SECURE
SECURE_HSTS_SECONDS = int(os.getenv("SECURE_HSTS_SECONDS", "0"))
SECURE_HSTS_INCLUDE_SUBDOMAINS = bool(SECURE_HSTS_SECONDS)
SECURE_HSTS_PRELOAD = bool(SECURE_HSTS_SECONDS)
SECURE_CONTENT_TYPE_NOSNIFF = True

# Пути ОС внутри контейнера
STATIC_ROOT = os.getenv("STATIC_ROOT", "/app/staticfiles")
MEDIA_ROOT = os.getenv("MEDIA_ROOT", "/app/media")

EXCHANGE_ROOT = os.getenv("EXCHANGE_ROOT", "/app/exchange")

# База — из окружения (docker-compose)
DATABASES["default"].update(  # noqa: F405
    {
        "NAME": os.getenv("DB_NAME", "ejournal"),
        "USER": os.getenv("DB_USER", "ejournal"),
        "PASSWORD": os.getenv("DB_PASSWORD", ""),
        "HOST": os.getenv("DB_HOST", "db"),
        "PORT": os.getenv("DB_PORT", "5432"),
    }
)

# Всегда включаем аудит
MIDDLEWARE.insert(0, "apps.core.middleware.AuditMiddleware")  # noqa: F405

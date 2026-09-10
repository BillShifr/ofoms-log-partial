"""Настройки боевого окружения (контейнер).

Включаются через DJANGO_SETTINGS_MODULE=config.settings.prod
(см. docker-compose / systemd unit). Все секреты — из переменных окружения.
"""

import os

from django.core.exceptions import ImproperlyConfigured

from .base import *  # noqa: F403

DEBUG = False


def _required_secret(name):
    value = os.getenv(name, "").strip()
    if (
        len(value) < 50
        or len(set(value)) < 5
        or value.startswith(("change-me", "django-insecure"))
    ):
        raise ImproperlyConfigured(
            f"{name} must contain at least 50 characters, at least 5 unique "
            "characters, and must not use a known development prefix."
        )
    return value


SECRET_KEY = _required_secret("SECRET_KEY")
JWT_SECRET = _required_secret("JWT_SECRET")

SECURE_SSL_REDIRECT = os.getenv("SECURE_SSL_REDIRECT", "True").lower() in (
    "1",
    "true",
    "yes",
)
SESSION_COOKIE_SECURE = os.getenv("SESSION_COOKIE_SECURE", "True").lower() in (
    "1",
    "true",
    "yes",
)
CSRF_COOKIE_SECURE = SESSION_COOKIE_SECURE
SECURE_HSTS_SECONDS = int(os.getenv("SECURE_HSTS_SECONDS", "31536000"))
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

# AuditMiddleware already belongs to the shared middleware chain in base.py.

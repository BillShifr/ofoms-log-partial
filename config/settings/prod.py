"""Настройки боевого окружения (контейнер).

Включаются через DJANGO_SETTINGS_MODULE=config.settings.prod
(см. docker-compose / systemd unit). Все секреты — из переменных окружения.
"""

import os

from django.core.exceptions import ImproperlyConfigured

from .base import *  # noqa: F403

DEBUG = False


def _required_secret(name, *, min_length=50, forbidden_prefixes=()):
    value = os.getenv(name, "").strip()
    if (
        len(value) < min_length
        or len(set(value)) < 5
        or value.lower().startswith(
            ("change-me", "django-insecure", *forbidden_prefixes)
        )
    ):
        raise ImproperlyConfigured(
            f"{name} must contain at least {min_length} characters, at least 5 unique "
            "characters, and must not use a known development prefix."
        )
    return value


def _bounded_int(name, default, *, minimum, maximum):
    raw_value = os.getenv(name, str(default)).strip()
    try:
        value = int(raw_value)
    except ValueError as error:
        raise ImproperlyConfigured(f"{name} must be an integer.") from error
    if not minimum <= value <= maximum:
        raise ImproperlyConfigured(
            f"{name} must be between {minimum} and {maximum}."
        )
    return value


SECRET_KEY = _required_secret("SECRET_KEY")
JWT_SECRET = _required_secret("JWT_SECRET")
DB_PASSWORD = _required_secret(
    "DB_PASSWORD",
    min_length=16,
    forbidden_prefixes=("ejournal", "postgres", "password"),
)
DB_POOL_MIN_SIZE = _bounded_int("DB_POOL_MIN_SIZE", 1, minimum=0, maximum=20)
DB_POOL_MAX_SIZE = _bounded_int("DB_POOL_MAX_SIZE", 4, minimum=1, maximum=50)
DB_POOL_TIMEOUT = _bounded_int("DB_POOL_TIMEOUT", 3, minimum=1, maximum=60)
DB_CONNECT_TIMEOUT = _bounded_int("DB_CONNECT_TIMEOUT", 3, minimum=1, maximum=60)
if DB_POOL_MIN_SIZE > DB_POOL_MAX_SIZE:
    raise ImproperlyConfigured("DB_POOL_MIN_SIZE must not exceed DB_POOL_MAX_SIZE.")

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

# Production topology terminates TLS at a trusted reverse proxy. The proxy must
# overwrite (not append) this header; the Compose port is loopback-bound by default.
if os.getenv("TRUST_PROXY_SSL_HEADER", "True").lower() in ("1", "true", "yes"):
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

# Пути ОС внутри контейнера
STATIC_ROOT = os.getenv("STATIC_ROOT", "/app/staticfiles")
MEDIA_ROOT = os.getenv("MEDIA_ROOT", "/app/media")

EXCHANGE_ROOT = os.getenv("EXCHANGE_ROOT", "/app/exchange")

# База — из окружения (docker-compose)
DATABASES["default"].update(  # noqa: F405
    {
        "NAME": os.getenv("DB_NAME", "ejournal"),
        "USER": os.getenv("DB_USER", "ejournal"),
        "PASSWORD": DB_PASSWORD,
        "HOST": os.getenv("DB_HOST", "db"),
        "PORT": os.getenv("DB_PORT", "5432"),
        "CONN_MAX_AGE": 0,
        "CONN_HEALTH_CHECKS": True,
        "OPTIONS": {
            "connect_timeout": DB_CONNECT_TIMEOUT,
            "pool": {
                "min_size": DB_POOL_MIN_SIZE,
                "max_size": DB_POOL_MAX_SIZE,
                "timeout": DB_POOL_TIMEOUT,
                "max_idle": 300,
                "max_lifetime": 1800,
            },
        },
    }
)

# AuditMiddleware already belongs to the shared middleware chain in base.py.

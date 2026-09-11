"""Настройки боевого окружения (контейнер).

Включаются через DJANGO_SETTINGS_MODULE=config.settings.prod
(см. docker-compose / systemd unit). Все секреты — из переменных окружения.
"""

import os
from urllib.parse import urlsplit

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


def _boolean_env(name, default):
    raw_value = os.getenv(name, "true" if default else "false").strip().lower()
    if raw_value in ("1", "true", "yes"):
        return True
    if raw_value in ("0", "false", "no"):
        return False
    raise ImproperlyConfigured(
        f"{name} must be one of: true, false, 1, 0, yes, no."
    )


def _production_hosts():
    hosts = [item.strip() for item in os.getenv("ALLOWED_HOSTS", "").split(",")]
    hosts = [item for item in hosts if item]
    invalid = [
        host
        for host in hosts
        if host == "*"
        or any(marker in host for marker in ("://", "/", "?", "#"))
        or any(character.isspace() for character in host)
    ]
    if not hosts or invalid:
        raise ImproperlyConfigured(
            "ALLOWED_HOSTS must contain explicit host names without schemes, paths, "
            "whitespace, or the '*' wildcard."
        )
    return hosts


def _trusted_token_origins():
    origins = []
    for raw_origin in os.getenv("TOKEN_LOGIN_TRUSTED_ORIGINS", "").split(","):
        origin = raw_origin.strip()
        if not origin:
            continue
        parsed = urlsplit(origin)
        if (
            parsed.scheme != "https"
            or not parsed.netloc
            or parsed.username
            or parsed.password
            or parsed.path not in ("", "/")
            or parsed.query
            or parsed.fragment
        ):
            raise ImproperlyConfigured(
                "TOKEN_LOGIN_TRUSTED_ORIGINS must contain HTTPS origins without "
                "credentials, paths, query strings, or fragments."
            )
        origins.append(f"https://{parsed.netloc.lower()}")
    return tuple(dict.fromkeys(origins))


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

ALLOWED_HOSTS = _production_hosts()
TOKEN_LOGIN_TRUSTED_ORIGINS = _trusted_token_origins()
SECURE_SSL_REDIRECT = _boolean_env("SECURE_SSL_REDIRECT", True)
SESSION_COOKIE_SECURE = _boolean_env("SESSION_COOKIE_SECURE", True)
CSRF_COOKIE_SECURE = SESSION_COOKIE_SECURE
SESSION_COOKIE_AGE = _bounded_int(
    "SESSION_COOKIE_AGE", 8 * 60 * 60, minimum=5 * 60, maximum=12 * 60 * 60
)
SESSION_EXPIRE_AT_BROWSER_CLOSE = True
SESSION_SAVE_EVERY_REQUEST = True
SECURE_HSTS_SECONDS = _bounded_int(
    "SECURE_HSTS_SECONDS", 31536000, minimum=0, maximum=63072000
)
SECURE_HSTS_INCLUDE_SUBDOMAINS = bool(SECURE_HSTS_SECONDS)
SECURE_HSTS_PRELOAD = bool(SECURE_HSTS_SECONDS)
SECURE_CONTENT_TYPE_NOSNIFF = True

# Production topology terminates TLS at a trusted reverse proxy. The proxy must
# overwrite (not append) this header; the Compose port is loopback-bound by default.
if _boolean_env("TRUST_PROXY_SSL_HEADER", True):
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

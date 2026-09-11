"""Базовые настройки Django для ИС «Единый электронный журнал обращений граждан» v2.

Архитектура: отдельные модули настроек config/settings/{base,dev,prod}.py.
Базовые параметры читаются из переменных окружения (.env) через python-dotenv.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent.parent

# Загрузка конфигурации окружения
load_dotenv(BASE_DIR / ".env")

# ---------------------------------------------------------------------------
# Безопасность
# ---------------------------------------------------------------------------
SECRET_KEY = os.getenv(
    "SECRET_KEY", "django-insecure-change-me-in-production-9f1c2a3b4d5e6f7a8b9c"
)

DEBUG = os.getenv("DEBUG", "False").lower() in ("1", "true", "yes")

ALLOWED_HOSTS = [
    h.strip()
    for h in os.getenv("ALLOWED_HOSTS", "localhost,127.0.0.1").split(",")
    if h.strip()
]

# ---------------------------------------------------------------------------
# Приложения (INSTALLED_APPS)
# ---------------------------------------------------------------------------
DJANGO_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.postgres",
]

THIRD_PARTY_APPS = [
    "rangefilter",
    "django_admin_listfilter_dropdown",
    "import_export",
]

LOCAL_APPS = [
    "apps.core",
    "apps.employee",
    "apps.journal",
    "apps.exchange",
    "apps.reports",
    "apps.system",
]

INSTALLED_APPS = DJANGO_APPS + THIRD_PARTY_APPS + LOCAL_APPS

# ---------------------------------------------------------------------------
# Middleware
# ---------------------------------------------------------------------------
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "apps.core.middleware.TrustedProxyClientIPMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "apps.core.middleware.AccountStateSessionMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "apps.core.middleware.ContentSecurityPolicyMiddleware",
    "apps.core.middleware.SensitiveResponseCacheMiddleware",
    # Приказ ФСТЭК № 17 (2 класс): аудит действий пользователя
    "apps.core.middleware.AuditMiddleware",
]

CONTENT_SECURITY_POLICY = (
    "default-src 'self'; "
    "script-src 'self'; "
    "style-src 'self'; "
    "img-src 'self' data:; "
    "font-src 'self'; "
    "connect-src 'self'; "
    "media-src 'self'; "
    "object-src 'none'; "
    "base-uri 'self'; "
    "form-action 'self'; "
    "frame-ancestors 'none'"
)

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "apps.core.context_processors.system_meta",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

# ---------------------------------------------------------------------------
# База данных (PostgreSQL, ТЗ разд.4/5)
# ---------------------------------------------------------------------------
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.getenv("DB_NAME", "ejournal"),
        "USER": os.getenv("DB_USER", "ejournal"),
        "PASSWORD": os.getenv("DB_PASSWORD", ""),
        "HOST": os.getenv("DB_HOST", "localhost"),
        "PORT": os.getenv("DB_PORT", "5432"),
        "CONN_MAX_AGE": 60,
    }
}

# ---------------------------------------------------------------------------
# Модель пользователя и аутентификация
# ---------------------------------------------------------------------------
AUTH_USER_MODEL = "employee.Employee"

LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "journal:list"
LOGOUT_REDIRECT_URL = "login"

AUTHENTICATION_BACKENDS = [
    "apps.core.auth.TFOMSAuthBackend",
]

# В dev/tests X-Forwarded-For считается недоверенным. Production включает его
# только вместе с контрактом reverse proxy, который обязан перезаписывать header.
TRUST_PROXY_CLIENT_IP_HEADER = False

# Парольная политика (ТЗ разд. 3.1): ≥8 символов, верх/низ/цифры/спецсимволы.
AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
        "OPTIONS": {"max_similarity": 0.5},
    },
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
        "OPTIONS": {"min_length": 8},
    },
    {
        "NAME": "django.contrib.auth.password_validation.CommonPasswordValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.NumericPasswordValidator",
    },
    {
        "NAME": "apps.core.validators.ComplexityPasswordValidator",
    },
]

# Блокировка доступа после N неудачных попыток (ТЗ разд. 3.1)
SECURITY_MAX_FAILED_LOGIN_ATTEMPTS = int(os.getenv("MAX_FAILED_LOGIN_ATTEMPTS", "10"))
SECURITY_FAILED_LOGIN_MEMORY = 15 * 60  # окно (сек) для накопления неудачных попыток

# Сквозная авторизация: временные токены
JWT_SECRET = os.getenv("JWT_SECRET", SECRET_KEY)
JWT_ALGORITHM = "HS256"
JWT_AUDIENCE = os.getenv("JWT_AUDIENCE", "ejournal").strip() or "ejournal"
JWT_TTL = int(os.getenv("JWT_TTL", "300"))  # сек — жизнь временного токена
TOKEN_LOGIN_TRUSTED_ORIGINS = tuple(
    origin.strip()
    for origin in os.getenv("TOKEN_LOGIN_TRUSTED_ORIGINS", "").split(",")
    if origin.strip()
)
TASK_STALE_AFTER_SECONDS = int(os.getenv("TASK_STALE_AFTER_SECONDS", "3600"))

# ---------------------------------------------------------------------------
# Локализация
# ---------------------------------------------------------------------------
LANGUAGE_CODE = "ru-RU"
TIME_ZONE = "Asia/Yekaterinburg"
USE_I18N = True
USE_TZ = False

# ---------------------------------------------------------------------------
# Статика и медиа
# ---------------------------------------------------------------------------
STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"
    },
}

MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

# Файлы обмена (см. Этап 3, каталоги v1: exchange/{in,out,archive}/<org>)
EXCHANGE_ROOT = BASE_DIR / "exchange"
EXCHANGE_IN = EXCHANGE_ROOT / "in"
EXCHANGE_OUT = EXCHANGE_ROOT / "out"
EXCHANGE_ARCHIVE = EXCHANGE_ROOT / "archive"

for _dir in (EXCHANGE_IN, EXCHANGE_OUT, EXCHANGE_ARCHIVE, MEDIA_ROOT):
    _dir.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# Логирование
# ---------------------------------------------------------------------------
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {
            "format": "{asctime} {levelname} {name}: {message}",
            "style": "{",
        },
    },
    "handlers": {
        "console": {"class": "logging.StreamHandler", "formatter": "verbose"},
    },
    "root": {"handlers": ["console"], "level": LOG_LEVEL},
    "loggers": {
        "django": {"handlers": ["console"], "level": LOG_LEVEL, "propagate": False},
        "apps": {"handlers": ["console"], "level": LOG_LEVEL, "propagate": False},
    },
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Системные параметры, видимые в шаблонах (core.context_processors.system_meta)
SYSTEM_META = {
    "SYSTEM_TITLE": "Единый электронный журнал обращений граждан",
    "SYSTEM_SHORT_TITLE": "ЭЖ обращений граждан",
    "SYSTEM_ORG": "ТФОМС ХМАО — Югры",
    "SITE_URL": os.getenv("SITE_URL", "http://localhost:8000"),
}

# Домен информационного ресурса (письмо ФФОМС: защищённый ресурс ТФОМС)
SESSION_COOKIE_HTTPONLY = True
CSRF_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SAMESITE = "Lax"
SECURE_REFERRER_POLICY = "same-origin"
X_FRAME_OPTIONS = "DENY"
SECURE_CONTENT_TYPE_NOSNIFF = True

"""Временные токены сквозной авторизации (внешние/внутренние подсистемы).

Единая сквозная авторизация (ТЗ разд. 3.1): внешний сервис (СМО, ведомства,
контакт-центр Минздрава) или внутренний сервис получает JWT на ограниченный
срок (JWT_TTL). Токен связывается с учётной записью Employee (by username/guid)
и проверяется в подсистеме единого входа при Этапе 5.
"""

import datetime as _dt
import uuid

import jwt
from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.core.models import ConsumedToken


class EmployeeRepository:
    """Адаптер единого репозитория учётных записей для token exchange."""

    def get_by_guid(self, guid):
        try:
            normalized_guid = uuid.UUID(str(guid))
        except (TypeError, ValueError, AttributeError):
            return None
        return get_user_model().objects.filter(guid=normalized_guid).first()


def issue_token(user, *, ttl: int | None = None, audience: str | None = None) -> str:
    """Выпуск временного JWT для вошедшего пользователя."""
    ttl = settings.JWT_TTL if ttl is None else ttl
    audience = settings.JWT_AUDIENCE if audience is None else audience
    now = _dt.datetime.now(tz=_dt.UTC)
    payload = {
        "sub": str(user.guid),
        "username": user.username,
        "aud": audience,
        "jti": str(uuid.uuid4()),
        "iat": now,
        "exp": now + _dt.timedelta(seconds=ttl),
    }
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


def decode_token(token: str, *, audience: str | None = None):
    """Декодирование. Возвращает payload; кидает jwt-исключения при ошибках."""
    audience = settings.JWT_AUDIENCE if audience is None else audience
    return jwt.decode(
        token,
        settings.JWT_SECRET,
        algorithms=[settings.JWT_ALGORITHM],
        audience=audience,
        options={"require": ["sub", "aud", "jti", "iat", "exp"]},
    )


def consume_token(payload: dict) -> bool:
    """Атомарно помечает JWT использованным; повторный jti отклоняет."""
    try:
        jti = uuid.UUID(str(payload["jti"]))
        expires_at = _dt.datetime.fromtimestamp(float(payload["exp"]), tz=_dt.UTC)
    except (KeyError, TypeError, ValueError, OverflowError):
        return False

    try:
        with transaction.atomic():
            ConsumedToken.objects.filter(expires_at__lt=timezone.now()).delete()
            ConsumedToken.objects.create(jti=jti, expires_at=expires_at)
    except IntegrityError:
        return False
    return True


def resolve_user(
    token: str,
    *,
    audience: str | None = None,
    repository: EmployeeRepository | None = None,
):
    """По токену возвращает Employee (или None)."""
    payload = decode_token(token, audience=audience)
    repository = repository or EmployeeRepository()
    return repository.get_by_guid(payload["sub"])

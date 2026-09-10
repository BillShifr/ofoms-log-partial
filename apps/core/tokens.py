"""Временные токены сквозной авторизации (внешние/внутренние подсистемы).

Единая сквозная авторизация (ТЗ разд. 3.1): внешний сервис (СМО, ведомства,
контакт-центр Минздрава) или внутренний сервис получает JWT на ограниченный
срок (JWT_TTL). Токен связывается с учётной записью Employee (by username/guid)
и проверяется в подсистеме единого входа при Этапе 5.
"""

import datetime as _dt

import jwt
from django.conf import settings
from django.contrib.auth import get_user_model


def issue_token(user, *, ttl: int | None = None, audience: str = "ejournal") -> str:
    """Выпуск временного JWT для вошедшего пользователя."""
    ttl = ttl or settings.JWT_TTL
    now = _dt.datetime.now(tz=_dt.UTC)
    payload = {
        "sub": str(user.guid),
        "username": user.username,
        "aud": audience,
        "iat": now,
        "exp": now + _dt.timedelta(seconds=ttl),
    }
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


def decode_token(token: str, *, audience: str = "ejournal"):
    """Декодирование. Возвращает payload; кидает jwt-исключения при ошибках."""
    return jwt.decode(
        token,
        settings.JWT_SECRET,
        algorithms=[settings.JWT_ALGORITHM],
        audience=audience,
    )


def resolve_user(token: str, *, audience: str = "ejournal"):
    """По токену возвращает Employee (или None)."""
    UserModel = get_user_model()
    payload = decode_token(token, audience=audience)
    return UserModel.objects.filter(guid=payload["sub"]).first()

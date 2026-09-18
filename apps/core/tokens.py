"""Временные токены сквозной авторизации (внешние/внутренние подсистемы).

Единая сквозная авторизация (ТЗ разд. 3.1): внешний сервис (СМО, ведомства,
контакт-центр Минздрава) или внутренний сервис получает JWT на ограниченный
срок (JWT_TTL). Токен связывается с учётной записью Employee (by username/guid)
и проверяется в подсистеме единого входа при Этапе 5.
"""

import datetime as _dt
import json
import math
import uuid
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

import jwt
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.db import IntegrityError, transaction

from apps.core.models import ConsumedToken
from apps.core.roles import GROUP_ROLE_MAP, SMO_ROLES, TFOMS_ROLES
from apps.employee.models import ORGS, TFOMS


class EmployeeRepository:
    """Локальный адаптер учетных записей для автономного режима."""

    def get_by_guid(self, guid):
        try:
            normalized_guid = uuid.UUID(str(guid))
        except (TypeError, ValueError, AttributeError):
            return None
        return get_user_model().objects.filter(guid=normalized_guid).first()


class HttpEmployeeRepository:
    """Синхронизирует локальную учетную запись с внешним REST-каталогом."""

    def __init__(self, *, base_url=None, token=None, timeout=None, opener=None):
        self.base_url = (base_url or settings.ACCOUNT_REPOSITORY_URL).rstrip("/")
        self.token = token if token is not None else settings.ACCOUNT_REPOSITORY_TOKEN
        self.timeout = timeout or settings.ACCOUNT_REPOSITORY_TIMEOUT
        self.opener = opener or urlopen

    def get_by_guid(self, guid):
        try:
            normalized_guid = uuid.UUID(str(guid))
        except (TypeError, ValueError, AttributeError):
            return None
        request = Request(
            f"{self.base_url}/employees/{quote(str(normalized_guid), safe='')}",
            headers={
                "Accept": "application/json",
                "Authorization": f"Bearer {self.token}",
            },
            method="GET",
        )
        try:
            with self.opener(request, timeout=self.timeout) as response:
                if getattr(response, "status", 200) != 200:
                    return None
                payload = json.load(response)
        except HTTPError as error:
            if error.code == 404:
                return None
            return None
        except (URLError, TimeoutError, OSError, ValueError, json.JSONDecodeError):
            return None
        return self._sync_user(normalized_guid, payload)

    @staticmethod
    def _sync_user(guid, payload):
        if not isinstance(payload, dict) or str(payload.get("guid", "")) != str(guid):
            return None
        username = str(payload.get("username", "")).strip()
        try:
            org = int(payload.get("org"))
        except (TypeError, ValueError):
            return None
        if not username or org not in dict(ORGS):
            return None
        roles = payload.get("roles", [])
        if not isinstance(roles, list) or any(not isinstance(role, str) for role in roles):
            return None
        allowed_codes = TFOMS_ROLES if org == TFOMS else SMO_ROLES
        if any(
            role not in GROUP_ROLE_MAP or GROUP_ROLE_MAP[role] not in allowed_codes
            for role in roles
        ):
            return None

        User = get_user_model()
        with transaction.atomic():
            username_owner = User.objects.select_for_update().filter(username=username).first()
            if username_owner is not None and username_owner.guid != guid:
                return None
            user, _created = User.objects.select_for_update().get_or_create(
                guid=guid,
                defaults={"username": username, "org": org},
            )
            user.username = username
            user.org = org
            user.first_name = str(payload.get("first_name", "")).strip()
            user.last_name = str(payload.get("last_name", "")).strip()
            user.job_title = str(payload.get("job_title", "")).strip() or None
            user.is_active = payload.get("is_active") is True
            user.is_staff = False
            user.is_superuser = False
            user.set_unusable_password()
            user.full_clean(exclude=("password",))
            user.save()
            user.groups.set(Group.objects.filter(name__in=roles))
            return user


def get_employee_repository():
    if settings.ACCOUNT_REPOSITORY_BACKEND == "http":
        return HttpEmployeeRepository()
    return EmployeeRepository()


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
    payload = jwt.decode(
        token,
        settings.JWT_SECRET,
        algorithms=[settings.JWT_ALGORITHM],
        audience=audience,
        options={"require": ["sub", "aud", "jti", "iat", "exp"]},
    )
    issued_at = payload["iat"]
    expires_at = payload["exp"]
    if isinstance(issued_at, bool) or isinstance(expires_at, bool):
        raise jwt.InvalidTokenError("JWT timestamps must be numeric.")
    try:
        issued_at = float(issued_at)
        expires_at = float(expires_at)
    except (TypeError, ValueError) as error:
        raise jwt.InvalidTokenError("JWT timestamps must be numeric.") from error
    lifetime = expires_at - issued_at
    if (
        not math.isfinite(issued_at)
        or not math.isfinite(expires_at)
        or lifetime <= 0
        or lifetime > settings.JWT_TTL
    ):
        raise jwt.InvalidTokenError("JWT lifetime exceeds the configured policy.")
    return payload


def consume_token(payload: dict) -> bool:
    """Атомарно помечает JWT использованным; повторный jti отклоняет."""
    try:
        jti = uuid.UUID(str(payload["jti"]))
        expires_at = _dt.datetime.fromtimestamp(float(payload["exp"]), tz=_dt.UTC)
    except (KeyError, TypeError, ValueError, OverflowError):
        return False

    try:
        with transaction.atomic():
            ConsumedToken.objects.filter(
                expires_at__lt=_dt.datetime.now(tz=_dt.UTC)
            ).delete()
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
    repository = repository or get_employee_repository()
    return repository.get_by_guid(payload["sub"])

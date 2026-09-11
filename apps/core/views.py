"""HTTP-точки общесистемных функций."""

import jwt
from django.conf import settings
from django.contrib.auth import login
from django.http import HttpResponseBadRequest, HttpResponseForbidden
from django.shortcuts import redirect
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from apps.core.tokens import EmployeeRepository, consume_token, decode_token

_MAX_TOKEN_LENGTH = 4096


def _request_token(request):
    authorization = request.headers.get("Authorization", "")
    if authorization:
        scheme, separator, value = authorization.partition(" ")
        if not separator or scheme.lower() != "bearer":
            return None
        return value.strip()
    return request.POST.get("token", "").strip()


def _redirect_target(request):
    target = request.POST.get("next", "")
    if target and url_has_allowed_host_and_scheme(
        target,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return target
    return reverse(settings.LOGIN_REDIRECT_URL)


@csrf_exempt
@require_POST
def token_login(request):
    """Обменивает краткоживущий JWT доверенной подсистемы на web-сессию."""
    token = _request_token(request)
    if not token or len(token) > _MAX_TOKEN_LENGTH:
        return HttpResponseBadRequest("Некорректный запрос.")

    try:
        payload = decode_token(token)
        user = EmployeeRepository().get_by_guid(payload["sub"])
    except (jwt.InvalidTokenError, KeyError, TypeError, ValueError):
        payload = None
        user = None

    if (
        user is None
        or not user.is_active
        or user.is_locked
        or payload is None
        or not consume_token(payload)
    ):
        response = HttpResponseForbidden("Вход по токену отклонён.")
    else:
        login(request, user, backend="apps.core.auth.TFOMSAuthBackend")
        response = redirect(_redirect_target(request))

    response.headers["Cache-Control"] = "no-store"
    response.headers["Referrer-Policy"] = "no-referrer"
    return response

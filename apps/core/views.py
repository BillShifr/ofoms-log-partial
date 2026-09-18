"""HTTP-точки общесистемных функций."""

from urllib.parse import urlsplit

import jwt
from django.conf import settings
from django.contrib.auth import login
from django.http import HttpResponseBadRequest, HttpResponseForbidden
from django.shortcuts import redirect
from django.urls import reverse
from django.utils.cache import patch_vary_headers
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from apps.core.tokens import consume_token, decode_token, get_employee_repository

_MAX_TOKEN_LENGTH = 4096


def _normalized_origin(value):
    parsed = urlsplit(value)
    if (
        parsed.scheme not in ("http", "https")
        or not parsed.netloc
        or parsed.username
        or parsed.password
        or parsed.path not in ("", "/")
        or parsed.query
        or parsed.fragment
    ):
        return None
    return f"{parsed.scheme.lower()}://{parsed.netloc.lower()}"


def _browser_origin_allowed(request):
    current_origin = f"{request.scheme.lower()}://{request.get_host().lower()}"
    trusted_origins = {current_origin, *settings.TOKEN_LOGIN_TRUSTED_ORIGINS}
    origin = request.headers.get("Origin")
    fetch_site = request.headers.get("Sec-Fetch-Site", "").lower()

    if origin:
        return _normalized_origin(origin) in trusted_origins
    if fetch_site == "cross-site":
        return False

    referer = request.headers.get("Referer")
    if referer:
        parsed = urlsplit(referer)
        referer_origin = _normalized_origin(
            f"{parsed.scheme}://{parsed.netloc}" if parsed.scheme and parsed.netloc else ""
        )
        return referer_origin in trusted_origins

    # Non-browser integrations commonly send neither Fetch Metadata nor Origin.
    return True


def _secure_token_response(response):
    response.headers["Cache-Control"] = "no-store"
    response.headers["Referrer-Policy"] = "no-referrer"
    patch_vary_headers(response, ("Origin", "Sec-Fetch-Site"))
    return response


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
    if not _browser_origin_allowed(request):
        return _secure_token_response(
            HttpResponseForbidden("Межсайтовый вход по токену отклонён.")
        )

    token = _request_token(request)
    if not token or len(token) > _MAX_TOKEN_LENGTH:
        return _secure_token_response(HttpResponseBadRequest("Некорректный запрос."))

    try:
        payload = decode_token(token)
        user = get_employee_repository().get_by_guid(payload["sub"])
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

    return _secure_token_response(response)

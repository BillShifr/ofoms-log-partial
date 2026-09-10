"""Сквозные (E2E) сценарии через реальный HTTP-стек (Этап 7).

Покрывают полный пользовательский путь с настоящими cookie/CSRF:
вход -> типовые экраны -> выход. Без JS (серверный рендеринг), stdlib urllib.
Запуск: pytest (LiveServerTestCase самостоятельно поднимает dev-сервер).
"""

import re
from http.cookiejar import CookieJar
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import HTTPCookieProcessor, Request, build_opener

from apps.core.models import EventLog
from apps.employee.models import Employee
from django.test import LiveServerTestCase

TOKEN_RE = re.compile(r'name="csrfmiddlewaretoken" value="([^"]+)"')
PASSWORD = "GoodPass!1"


class _LiveHttp:
    def __init__(self, base_url):
        self.base = base_url.rstrip("/")
        self._jar = CookieJar()
        self._opener = build_opener(HTTPCookieProcessor(self._jar))

    def get(self, path):
        with self._opener.open(self.base + path, timeout=20) as resp:
            return resp.status, resp.read().decode("utf-8", errors="replace")

    def post_form(self, path, data, token_page):
        status, html = self.get(token_page)
        match = TOKEN_RE.search(html)
        if match is None:
            raise AssertionError(f"CSRF-токен не найден на {token_page}")
        body = urlencode({**data, "csrfmiddlewaretoken": match.group(1)}).encode()
        req = Request(
            self.base + path,
            data=body,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        try:
            with self._opener.open(req, timeout=20) as resp:
                code = resp.status
                html = resp.read().decode("utf-8", errors="replace")
        except HTTPError as exc:
            code = exc.code
            html = exc.read().decode("utf-8", errors="replace")
        return code, html


class LiveFlowsTests(LiveServerTestCase):
    def setUp(self):
        self.operator = Employee.objects.create_user(
            username="e2e_op", password=PASSWORD, org=81000
        )

    def _client(self):
        return _LiveHttp(self.live_server_url)

    def test_full_user_flow_via_http(self):
        http = self._client()

        status, html = http.get("/accounts/login/")
        self.assertEqual(status, 200)

        status, html = http.post_form(
            "/accounts/login/?next=/journal/",
            {"username": "e2e_op", "password": PASSWORD},
            token_page="/accounts/login/",
        )
        self.assertEqual(status, 200)
        self.assertIn("Единый электронный журнал обращений граждан", html)
        self.assertTrue(
            EventLog.objects.filter(
                event_type=EventLog.EventType.LOGIN, user=self.operator
            ).exists()
        )

        for path, expected in (
            ("/journal/", "Единый электронный журнал обращений граждан"),
            ("/system/messages/", "Сообщения"),
            ("/system/news/", "Новости"),
        ):
            status, html = http.get(path)
            self.assertEqual(status, 200)
            self.assertIn(expected, html)

        status, html = http.post_form("/accounts/logout/", {}, token_page="/system/messages/")
        self.assertEqual(status, 200)
        status, html = http.get("/journal/")
        self.assertEqual(status, 200)
        self.assertIn("Вход в систему", html)

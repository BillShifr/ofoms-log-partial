"""Сквозные (E2E) сценарии через реальный HTTP-стек (Этап 7).

Покрывают полный пользовательский путь с настоящими cookie/CSRF:
вход -> типовые экраны -> выход. Без JS (серверный рендеринг), stdlib urllib.
Запуск: pytest (LiveServerTestCase самостоятельно поднимает dev-сервер).
"""

import datetime
import re
from http.cookiejar import CookieJar
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import HTTPCookieProcessor, Request, build_opener

from apps.core.models import EventLog
from apps.core.roles import ensure_role_groups
from apps.employee.models import Employee
from apps.journal.models import Irp, IrpTheme
from apps.system.models import (
    Conversation,
    MessageReply,
    MessageThread,
    NewsItem,
    TaskJob,
    TaskNote,
    TaskReport,
)
from django.contrib.auth.models import Group
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

    def get_bytes(self, path):
        with self._opener.open(self.base + path, timeout=20) as resp:
            return resp.status, resp.headers, resp.read()

    def post_form(self, path, data, token_page):
        status, html = self.get(token_page)
        match = TOKEN_RE.search(html)
        if match is None:
            raise AssertionError(f"CSRF-токен не найден на {token_page}")
        body = urlencode(
            {**data, "csrfmiddlewaretoken": match.group(1)}, doseq=True
        ).encode()
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
        ensure_role_groups()
        self.operator = Employee.objects.create_user(
            username="e2e_op", password=PASSWORD, org=81000
        )
        self.operator.groups.add(Group.objects.get(name="ОП1"))
        self.recipient = Employee.objects.create_user(
            username="e2e_recipient", password=PASSWORD, org=81001
        )
        self.recipient.groups.add(Group.objects.get(name="СП1"))
        self.admin = Employee.objects.create_user(
            username="e2e_admin", password=PASSWORD, org=81000, is_staff=True
        )
        self.admin.groups.add(Group.objects.get(name="Администратор"))
        self.theme = IrpTheme.objects.create(
            code_name="E2E.01", title="Сквозная проверка", version=3
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

    def test_journal_create_edit_close_flow_via_http(self):
        http = self._client()
        status, _ = http.post_form(
            "/accounts/login/?next=/journal/new/",
            {"username": self.operator.username, "password": PASSWORD},
            token_page="/accounts/login/",
        )
        self.assertEqual(status, 200)

        today = datetime.date.today()
        planned = today + datetime.timedelta(days=30)
        create_data = {
            "irp_type": 2,
            "date_create": today.isoformat(),
            "way": 1,
            "how": 2,
            "theme": self.theme.pk,
            "otv_t": 1,
            "otv_kon": self.operator.org,
            "employee_one": self.operator.pk,
            "line_one": 1,
            "data_plan": planned.isoformat(),
            "z_f": "Сквозной",
            "z_i": "Тест",
            "text": "Создано через реальный HTTP-стек",
        }
        status, html = http.post_form(
            "/journal/new/", create_data, token_page="/journal/new/"
        )
        self.assertEqual(status, 200)
        self.assertIn("Сквозной", html)

        irp = Irp.objects.get(z_f="Сквозной")
        self.assertEqual(irp.status, Irp.Status.REGISTERED)

        edit_data = {
            **create_data,
            "n_irp": str(irp.n_irp),
            "z_f": "Сквозной-изменён",
            "date_close": today.isoformat(),
            "result": 2,
        }
        status, html = http.post_form(
            f"/journal/{irp.pk}/edit/",
            edit_data,
            token_page=f"/journal/{irp.pk}/edit/",
        )
        self.assertEqual(status, 200)
        self.assertIn("Закрыто", html)
        self.assertIn("Сквозной-изменён", html)

        irp.refresh_from_db()
        self.assertEqual(irp.status, Irp.Status.CLOSED)
        self.assertEqual(irp.result, 2)

        status, html = http.get(
            f"/reports/r1_volume/?date_from={today.isoformat()}"
        )
        self.assertEqual(status, 200)
        self.assertIn("Количество поступивших обращений", html)
        self.assertIn("ИТОГО", html)
        self.assertNotIn(">None<", html)

        status, headers, payload = http.get_bytes(
            f"/reports/r1_volume/export/xlsx/?date_from={today.isoformat()}"
        )
        self.assertEqual(status, 200)
        self.assertEqual(
            headers.get_content_type(),
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        self.assertTrue(payload.startswith(b"PK"))

    def test_conversation_thread_reply_flow_via_http(self):
        http = self._client()
        status, _ = http.post_form(
            "/accounts/login/?next=/system/messages/",
            {"username": self.operator.username, "password": PASSWORD},
            token_page="/accounts/login/",
        )
        self.assertEqual(status, 200)

        status, html = http.post_form(
            "/system/messages/new/",
            {"title": "Сквозной диалог", "participants": [self.recipient.pk]},
            token_page="/system/messages/",
        )
        self.assertEqual(status, 200)
        self.assertIn("Сквозной диалог", html)
        conversation = Conversation.objects.get(title="Сквозной диалог")
        self.assertSetEqual(
            set(conversation.participants.values_list("pk", flat=True)),
            {self.operator.pk, self.recipient.pk},
        )

        status, html = http.post_form(
            f"/system/messages/conversation/{conversation.pk}/threads/new/",
            {"title": "Проверка обработки"},
            token_page=f"/system/messages/conversation/{conversation.pk}/",
        )
        self.assertEqual(status, 200)
        self.assertIn("Проверка обработки", html)
        thread = MessageThread.objects.get(conversation=conversation)

        status, html = http.post_form(
            f"/system/messages/thread/{thread.pk}/reply/",
            {"body": "Результат сквозной проверки получен"},
            token_page=f"/system/messages/thread/{thread.pk}/",
        )
        self.assertEqual(status, 200)
        self.assertIn("Результат сквозной проверки получен", html)
        self.assertTrue(
            MessageReply.objects.filter(thread=thread, author=self.operator).exists()
        )

    def test_admin_news_task_and_user_flow_via_http(self):
        http = self._client()
        status, _ = http.post_form(
            "/accounts/login/?next=/system/news/",
            {"username": self.admin.username, "password": PASSWORD},
            token_page="/accounts/login/",
        )
        self.assertEqual(status, 200)

        status, html = http.post_form(
            "/system/news/new/",
            {
                "title": "Новость сквозной проверки",
                "summary": "Краткий результат",
                "text": "Публикация создана через HTTP",
                "is_active": "on",
            },
            token_page="/system/news/",
        )
        self.assertEqual(status, 200)
        self.assertIn("Новость сквозной проверки", html)
        news = NewsItem.objects.get(title="Новость сквозной проверки")
        self.assertTrue(news.is_active)

        status, html = http.post_form(
            "/system/tasks/new/",
            {
                "name": "Сквозная задача",
                "command": "noop",
                "description": "Проверка жизненного цикла",
                "status": TaskJob.Status.CREATED,
                "assigned_to": self.operator.pk,
                "priority": TaskJob.Priority.MEDIUM,
                "run_mode": TaskJob.RunMode.MANUAL,
                "enabled": "on",
            },
            token_page="/system/tasks/new/",
        )
        self.assertEqual(status, 200)
        self.assertIn("Сквозная задача", html)
        task = TaskJob.objects.get(name="Сквозная задача")

        status, html = http.post_form(
            f"/system/tasks/{task.pk}/",
            {"action": "note", "text": "Ход выполнения проверен"},
            token_page=f"/system/tasks/{task.pk}/",
        )
        self.assertEqual(status, 200)
        self.assertIn("Ход выполнения проверен", html)
        self.assertTrue(TaskNote.objects.filter(task=task).exists())

        status, html = http.post_form(
            f"/system/tasks/{task.pk}/",
            {
                "action": "report",
                "title": "Результат проверки",
                "content": "Сквозной сценарий завершён",
            },
            token_page=f"/system/tasks/{task.pk}/",
        )
        self.assertEqual(status, 200)
        self.assertIn("Результат проверки", html)
        self.assertTrue(TaskReport.objects.filter(task=task).exists())

        sp1_group = Group.objects.get(name="СП1")
        status, html = http.post_form(
            "/system/users/new/",
            {
                "username": "e2e_created_user",
                "password1": PASSWORD,
                "password2": PASSWORD,
                "last_name": "Созданный",
                "first_name": "Пользователь",
                "org": 81001,
                "roles": [sp1_group.pk],
            },
            token_page="/system/users/new/",
        )
        self.assertEqual(status, 200)
        self.assertIn("e2e_created_user", html)
        created = Employee.objects.get(username="e2e_created_user")
        self.assertTrue(created.groups.filter(pk=sp1_group.pk).exists())

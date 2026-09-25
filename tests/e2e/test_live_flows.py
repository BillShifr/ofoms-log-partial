"""Сквозные (E2E) сценарии через реальный HTTP-стек (этап 4 плана готовности).

Покрывают пользовательские пути с настоящими cookie/CSRF и multipart-загрузками:
вход -> создание -> изменение/результат -> выход. Без JS, stdlib urllib.
Запуск: pytest (LiveServerTestCase самостоятельно поднимает dev-сервер).
"""

import datetime
import json
import re
import tempfile
import threading
import uuid
from http.cookiejar import CookieJar
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import HTTPCookieProcessor, Request, build_opener

from apps.core.models import ConsumedToken, EventLog
from apps.core.roles import ensure_role_groups
from apps.core.tokens import issue_token
from apps.employee.models import Employee
from apps.exchange.models import ImportLog
from apps.journal.models import Irp, IrpTheme
from apps.system.models import (
    Conversation,
    MessageAttachment,
    MessageReply,
    MessageThread,
    NewsItem,
    SystemDocument,
    TaskJob,
    TaskNote,
    TaskReport,
    UserTableViewPref,
)
from django.contrib.auth.models import Group
from django.core.management import call_command
from django.test import LiveServerTestCase, override_settings
from lxml import etree

TOKEN_RE = re.compile(r'name="csrfmiddlewaretoken" value="([^"]+)"')
PASSWORD = "GoodPass!1"
SAMPLE_USERS_XML = """<?xml version="1.0" encoding="windows-1251"?>
<USER_COLLECTION>
  <USERS>
    <USER_FULLNAME>Файлов Файл Файлович</USER_FULLNAME>
    <USER_UUID>00000000-0000-0000-0000-00000000e2e1</USER_UUID>
    <USER_EMAIL>file-e2e@example.ru</USER_EMAIL>
  </USERS>
</USER_COLLECTION>
""".encode("windows-1251")


def _invalid_irp_xml(theme_code, employee_guid):
    return f"""<?xml version="1.0" encoding="windows-1251"?>
<IRP_LIST>
  <ZGLV><filename>G1R_E2E_INVALID.xml</filename><year>2026</year><month>09</month><day>18</day><smo>81000</smo></ZGLV>
  <IRP>
    <n_irp>{uuid.uuid4()}</n_irp><irp_type>1</irp_type><date_create>2026-09-18</date_create>
    <way>5</way><how>2</how><theme>{theme_code}</theme><otv_t>1</otv_t>
    <otv_kon>81000</otv_kon><employee_1>{employee_guid}</employee_1><data_plan>2026-10-18</data_plan>
  </IRP>
</IRP_LIST>
""".encode("windows-1251")


class _LiveHttp:
    def __init__(self, base_url):
        self.base = base_url.rstrip("/")
        self._jar = CookieJar()
        self._opener = build_opener(HTTPCookieProcessor(self._jar))

    def get(self, path):
        try:
            with self._opener.open(self.base + path, timeout=20) as resp:
                return resp.status, resp.read().decode("utf-8", errors="replace")
        except HTTPError as exc:
            return exc.code, exc.read().decode("utf-8", errors="replace")

    def get_bytes(self, path):
        try:
            with self._opener.open(self.base + path, timeout=20) as resp:
                return resp.status, resp.headers, resp.read()
        except HTTPError as exc:
            return exc.code, exc.headers, exc.read()

    def post_without_csrf(self, path, data):
        request = Request(
            self.base + path,
            data=urlencode(data, doseq=True).encode(),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        try:
            with self._opener.open(request, timeout=20) as response:
                return response.status, response.read().decode("utf-8", errors="replace")
        except HTTPError as exc:
            return exc.code, exc.read().decode("utf-8", errors="replace")

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

    def post_multipart(self, path, data, files, token_page):
        _, html = self.get(token_page)
        match = TOKEN_RE.search(html)
        if match is None:
            raise AssertionError(f"CSRF-токен не найден на {token_page}")
        boundary = f"----ofoms-e2e-{uuid.uuid4().hex}"
        chunks = []
        for name, value in {**data, "csrfmiddlewaretoken": match.group(1)}.items():
            chunks.extend(
                [
                    f"--{boundary}\r\n".encode(),
                    f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode(),
                    str(value).encode(),
                    b"\r\n",
                ]
            )
        for name, (filename, payload, content_type) in files.items():
            chunks.extend(
                [
                    f"--{boundary}\r\n".encode(),
                    (
                        f'Content-Disposition: form-data; name="{name}"; '
                        f'filename="{filename}"\r\n'
                    ).encode(),
                    f"Content-Type: {content_type}\r\n\r\n".encode(),
                    payload,
                    b"\r\n",
                ]
            )
        chunks.append(f"--{boundary}--\r\n".encode())
        request = Request(
            self.base + path,
            data=b"".join(chunks),
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        )
        try:
            with self._opener.open(request, timeout=20) as response:
                return response.status, response.read().decode("utf-8", errors="replace")
        except HTTPError as exc:
            return exc.code, exc.read().decode("utf-8", errors="replace")


class LiveFlowsTests(LiveServerTestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory(prefix="ofoms-e2e-")
        root = Path(self.temp_dir.name)
        self.settings_override = override_settings(
            MEDIA_ROOT=root / "media",
            EXCHANGE_IN=root / "exchange" / "in",
            EXCHANGE_OUT=root / "exchange" / "out",
            EXCHANGE_ARCHIVE=root / "exchange" / "archive",
        )
        self.settings_override.enable()
        self.addCleanup(self.settings_override.disable)
        self.addCleanup(self.temp_dir.cleanup)
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
            username="e2e_admin",
            password=PASSWORD,
            org=81000,
            is_staff=True,
            is_superuser=True,
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
                "command": "database_health",
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

    def test_document_and_exchange_upload_flow_via_http(self):
        http = self._client()
        status, _ = http.post_form(
            "/accounts/login/?next=/system/docs/",
            {"username": self.admin.username, "password": PASSWORD},
            token_page="/accounts/login/",
        )
        self.assertEqual(status, 200)

        status, html = http.post_multipart(
            "/system/docs/upload/",
            {
                "title": "Документ сквозной проверки",
                "version": "1.0",
                "sort_order": 0,
            },
            {"file": ("e2e-manual.pdf", b"%PDF-1.4\n%%EOF\n", "application/pdf")},
            token_page="/system/docs/",
        )
        self.assertEqual(status, 200)
        self.assertIn("Документ сквозной проверки", html)
        document = SystemDocument.objects.get(title="Документ сквозной проверки")
        self.assertTrue(Path(document.file.path).exists())

        status, html = http.post_multipart(
            "/exchange/upload/",
            {"org": self.admin.org},
            {
                "file": (
                    "users260911001.xml",
                    SAMPLE_USERS_XML,
                    "application/xml",
                )
            },
            token_page="/exchange/upload/",
        )
        self.assertEqual(status, 200)
        self.assertIn("Протокол", html)
        exchange_log = ImportLog.objects.get(filename="users260911001.xml")
        self.assertEqual(exchange_log.status, ImportLog.Status.OK)
        self.assertTrue(Employee.objects.filter(email="file-e2e@example.ru").exists())

    def test_table_preferences_groups_and_user_assignment_flow_via_http(self):
        http = self._client()
        status, _ = http.post_form(
            "/accounts/login/?next=/system/groups/",
            {"username": self.admin.username, "password": PASSWORD},
            token_page="/accounts/login/",
        )
        self.assertEqual(status, 200)

        status, html = http.post_form(
            "/system/groups/", {"name": "Приёмочный контроль"},
            token_page="/system/groups/",
        )
        self.assertEqual(status, 200)
        self.assertIn("Приёмочный контроль", html)
        additional = Group.objects.get(name="Приёмочный контроль")

        status, _ = http.post_form(
            "/system/prefs/system-groups/?modal=1",
            {
                "columns": ["member_count", "name", "actions"],
                "order_member_count": 1,
                "order_name": 2,
                "order_actions": 3,
                "sort_field": "member_count",
                "sort_dir": "-",
                "pinned_columns": ["member_count", "name", "type"],
                "grouped_headers": ["Группа", "Состав", "Несуществующая"],
            },
            token_page="/system/groups/",
        )
        self.assertEqual(status, 200)
        pref = UserTableViewPref.objects.get(
            user=self.admin, table_key="system-groups"
        )
        self.assertEqual(pref.columns, ["member_count", "name", "actions"])
        self.assertEqual(pref.pinned_columns, ["member_count", "name"])
        self.assertEqual(pref.grouped_headers, ["Группа", "Состав"])

        status, html = http.post_form(
            "/system/users/new/",
            {
                "username": "e2e_group_member",
                "password1": PASSWORD,
                "password2": PASSWORD,
                "last_name": "Групповой",
                "first_name": "Участник",
                "org": 81000,
                "roles": [Group.objects.get(name="ОП1").pk],
                "additional_groups": [additional.pk],
            },
            token_page="/system/users/new/",
        )
        self.assertEqual(status, 200)
        self.assertIn("e2e_group_member", html)
        member = Employee.objects.get(username="e2e_group_member")
        self.assertTrue(member.groups.filter(pk=additional.pk).exists())

        status, _ = http.post_form(
            f"/system/groups/{additional.pk}/delete/", {},
            token_page="/system/groups/",
        )
        self.assertEqual(status, 200)
        self.assertFalse(Group.objects.filter(pk=additional.pk).exists())
        self.assertTrue(
            EventLog.objects.filter(target__contains="Приёмочный контроль").exists()
        )

    def test_real_task_queue_worker_and_audit_flow_via_http(self):
        expired = ConsumedToken.objects.create(
            jti=uuid.uuid4(),
            expires_at=datetime.datetime.now(tz=datetime.UTC)
            - datetime.timedelta(minutes=1),
        )
        http = self._client()
        status, _ = http.post_form(
            "/accounts/login/?next=/system/tasks/new/",
            {"username": self.admin.username, "password": PASSWORD},
            token_page="/accounts/login/",
        )
        self.assertEqual(status, 200)
        status, html = http.post_form(
            "/system/tasks/new/",
            {
                "name": "Очистка токенов E2E",
                "command": "expired_token_cleanup",
                "description": "Реальное выполнение через очередь",
                "priority": TaskJob.Priority.HIGH,
                "run_mode": TaskJob.RunMode.MANUAL,
                "max_retries": 1,
                "retry_delay_seconds": 0,
                "param__expired_token_cleanup__batch_size": 10,
                "enabled": "on",
            },
            token_page="/system/tasks/new/",
        )
        self.assertEqual(status, 200)
        self.assertIn("Очистка токенов E2E", html)
        task = TaskJob.objects.get(name="Очистка токенов E2E")
        self.assertEqual(task.params, {"batch_size": 10})

        status, html = http.post_form(
            f"/system/tasks/{task.pk}/run/", {},
            token_page=f"/system/tasks/{task.pk}/",
        )
        self.assertEqual(status, 200)
        self.assertIn("поставлено в очередь", html)
        task.refresh_from_db()
        self.assertEqual(task.status, TaskJob.Status.QUEUED)

        call_command("run_tasks", limit=10)
        task.refresh_from_db()
        run = task.runs.get()
        self.assertEqual(task.status, TaskJob.Status.COMPLETED)
        self.assertEqual(run.result, "ok")
        self.assertIn("Удалено истёкших", run.log)
        self.assertFalse(ConsumedToken.objects.filter(pk=expired.pk).exists())
        self.assertIsNotNone(run.audit_event.finished_at)

        status, html = http.get(f"/system/tasks/{task.pk}/")
        self.assertEqual(status, 200)
        self.assertIn("успешно", html.lower())
        self.assertIn("Удалено истёкших", html)

    def test_repeat_outbound_contract_and_org_isolation_flow_via_http(self):
        original = Irp.objects.create(
            n_irp=str(uuid.uuid4()), irp_type=1,
            date_create=datetime.date.today(), way=1, how=1,
            theme=self.theme, otv_t=2, otv_kon=81001,
            employee_one=self.operator, employee_it=self.recipient,
            line_one=1, line_it=3,
            data_plan=datetime.date.today() + datetime.timedelta(days=30),
            z_f="Первичное",
        )
        http = self._client()
        status, _ = http.post_form(
            "/accounts/login/?next=/journal/new/",
            {"username": self.operator.username, "password": PASSWORD},
            token_page="/accounts/login/",
        )
        self.assertEqual(status, 200)
        status, html = http.post_form(
            "/journal/new/",
            {
                "irp_type": 1,
                "date_create": datetime.date.today().isoformat(),
                "repeat_of": original.pk,
                "way": 1,
                "how": 1,
                "theme": self.theme.pk,
                "otv_t": 1,
                "otv_kon": 81000,
                "line_one": 1,
                "data_plan": (
                    datetime.date.today() + datetime.timedelta(days=30)
                ).isoformat(),
                "z_f": "Повторное",
            },
            token_page="/journal/new/",
        )
        self.assertEqual(status, 200)
        self.assertIn("Повторное обращение", html)
        repeat = Irp.objects.get(z_f="Повторное")
        self.assertEqual(repeat.repeat_of, original)
        self.assertEqual(repeat.employee_it, self.recipient)
        self.assertEqual(repeat.otv_kon, original.otv_kon)

        status, headers, payload = http.get_bytes("/exchange/export/?org=81000")
        self.assertEqual(status, 200)
        self.assertEqual(
            headers["X-Exchange-Contract"], "tfoms-journal-current/1.0"
        )
        root = etree.fromstring(payload)
        schema = etree.XMLSchema(
            etree.parse("apps/exchange/contracts/journal-outbound-v1.xsd")
        )
        self.assertTrue(schema.validate(root), schema.error_log)
        self.assertEqual(root.xpath("count(IRP)"), 2.0)

        foreign = self._client()
        status, _ = foreign.post_form(
            "/accounts/login/?next=/exchange/logs/",
            {"username": self.recipient.username, "password": PASSWORD},
            token_page="/accounts/login/",
        )
        self.assertEqual(status, 200)
        status, _, _ = foreign.get_bytes("/exchange/export/?org=81000")
        self.assertEqual(status, 403)

    def test_message_attachment_close_reopen_and_access_flow_via_http(self):
        http = self._client()
        status, _ = http.post_form(
            "/accounts/login/?next=/system/messages/",
            {"username": self.operator.username, "password": PASSWORD},
            token_page="/accounts/login/",
        )
        self.assertEqual(status, 200)
        http.post_form(
            "/system/messages/new/",
            {"title": "Диалог с вложением", "participants": [self.recipient.pk]},
            token_page="/system/messages/",
        )
        conversation = Conversation.objects.get(title="Диалог с вложением")
        http.post_form(
            f"/system/messages/conversation/{conversation.pk}/threads/new/",
            {"title": "Документы"},
            token_page=f"/system/messages/conversation/{conversation.pk}/",
        )
        thread = MessageThread.objects.get(conversation=conversation)

        status, html = http.post_multipart(
            f"/system/messages/thread/{thread.pk}/reply/",
            {"body": "Файл приложен"},
            {"attachment": ("evidence.pdf", b"%PDF-1.4\n%%EOF", "application/pdf")},
            token_page=f"/system/messages/thread/{thread.pk}/",
        )
        self.assertEqual(status, 200)
        self.assertIn("evidence.pdf", html)
        attachment = MessageAttachment.objects.get(reply__thread=thread)
        status, _, payload = http.get_bytes(
            f"/system/messages/attachments/{attachment.pk}/download/"
        )
        self.assertEqual(status, 200)
        self.assertTrue(payload.startswith(b"%PDF"))

        outsider = Employee.objects.create_user(
            username="e2e_outsider", password=PASSWORD, org=81001
        )
        outsider.groups.add(Group.objects.get(name="СП1"))
        outsider_http = self._client()
        outsider_http.post_form(
            "/accounts/login/?next=/system/messages/",
            {"username": outsider.username, "password": PASSWORD},
            token_page="/accounts/login/",
        )
        status, _, _ = outsider_http.get_bytes(
            f"/system/messages/attachments/{attachment.pk}/download/"
        )
        self.assertEqual(status, 403)

        status, html = http.post_form(
            f"/system/messages/thread/{thread.pk}/toggle/", {},
            token_page=f"/system/messages/thread/{thread.pk}/",
        )
        self.assertEqual(status, 200)
        self.assertIn("Тема закрыта", html)
        status, _ = http.post_form(
            f"/system/messages/thread/{thread.pk}/reply/",
            {"body": "Не должно сохраниться"},
            token_page=f"/system/messages/thread/{thread.pk}/",
        )
        self.assertEqual(status, 403)
        self.assertFalse(MessageReply.objects.filter(body="Не должно сохраниться").exists())

        status, html = http.post_form(
            f"/system/messages/thread/{thread.pk}/toggle/", {},
            token_page=f"/system/messages/thread/{thread.pk}/",
        )
        self.assertEqual(status, 200)
        self.assertIn("Тема снова открыта", html)

        before = MessageReply.objects.filter(thread=thread).count()
        status, html = http.post_multipart(
            f"/system/messages/thread/{thread.pk}/reply/",
            {"body": "Опасное вложение"},
            {"attachment": ("payload.php", b"<?php", "application/octet-stream")},
            token_page=f"/system/messages/thread/{thread.pk}/",
        )
        self.assertEqual(status, 200)
        self.assertIn("Недопустимый тип вложения", html)
        self.assertEqual(MessageReply.objects.filter(thread=thread).count(), before)

    def test_unified_flc_and_exchange_pagination_flow_via_http(self):
        http = self._client()
        status, _ = http.post_form(
            "/accounts/login/?next=/journal/new/",
            {"username": self.operator.username, "password": PASSWORD},
            token_page="/accounts/login/",
        )
        self.assertEqual(status, 200)
        invalid_data = {
            "n_irp": "e2e-invalid-way",
            "irp_type": 1,
            "date_create": "2026-09-18",
            "way": 5,
            "how": 2,
            "theme": self.theme.pk,
            "otv_t": 1,
            "otv_kon": 81000,
            "line_one": 1,
            "data_plan": "2026-10-18",
            "z_f": "Не сохранять",
        }
        status, html = http.post_form(
            "/journal/new/", invalid_data, token_page="/journal/new/"
        )
        self.assertEqual(status, 200)
        self.assertIn("Укажите организацию-источник", html)
        self.assertIn("Не сохранять", html)
        self.assertFalse(Irp.objects.filter(n_irp="e2e-invalid-way").exists())

        status, html = http.post_multipart(
            "/exchange/upload/",
            {"org": 81000},
            {
                "file": (
                    "G1R_E2E_INVALID.xml",
                    _invalid_irp_xml(self.theme.code_name, self.operator.guid),
                    "application/xml",
                )
            },
            token_page="/exchange/upload/",
        )
        self.assertEqual(status, 200)
        self.assertIn("Укажите организацию-источник", html)
        log = ImportLog.objects.get(filename="G1R_E2E_INVALID.xml")
        self.assertEqual(log.status, ImportLog.Status.ERROR)

        ImportLog.objects.bulk_create(
            [
                ImportLog(
                    org=81000, kind=ImportLog.Kind.IRP,
                    filename=f"e2e-page-{index:02d}.xml",
                    status=ImportLog.Status.OK, rows=1,
                )
                for index in range(31)
            ]
        )
        status, html = http.get("/exchange/logs/?page=2")
        self.assertEqual(status, 200)
        self.assertIn("Стр. 2 из 2", html)
        self.assertIn("e2e-page-00.xml", html)

    def test_role_ui_denial_and_external_repository_sso_flow_via_http(self):
        limited = Employee.objects.create_user(
            username="e2e_limited", password=PASSWORD, org=81001
        )
        limited.groups.add(Group.objects.get(name="СП2"))
        limited_http = self._client()
        status, html = limited_http.post_form(
            "/accounts/login/?next=/journal/",
            {"username": limited.username, "password": PASSWORD},
            token_page="/accounts/login/",
        )
        self.assertEqual(status, 200)
        self.assertNotIn("Новое обращение", html)
        self.assertIn("Новая тема", html)
        status, payload = limited_http.post_form(
            "/journal/themes/new/",
            {"code_name": "e2e.limited", "title": "Тема ограниченной роли"},
            token_page="/journal/",
        )
        self.assertEqual(status, 201)
        self.assertTrue(json.loads(payload)["ok"])
        self.assertTrue(IrpTheme.objects.filter(code_name="E2E.LIMITED").exists())
        self.assertEqual(limited_http.get("/journal/new/")[0], 403)
        self.assertEqual(limited_http.get("/exchange/upload/")[0], 403)
        self.assertEqual(limited_http.get("/system/users/")[0], 403)

        guid = uuid.uuid4()
        token_source = Employee.objects.create_user(
            username="temporary-token-source", org=81001, guid=guid
        )
        token = issue_token(token_source)
        token_source.delete()
        payload = {
            "guid": str(guid),
            "username": "external_e2e_user",
            "org": 81001,
            "first_name": "Внешний",
            "last_name": "Пользователь",
            "job_title": "Специалист",
            "is_active": True,
            "roles": ["СП1"],
        }

        class RepositoryHandler(BaseHTTPRequestHandler):
            def do_GET(self):
                if (
                    self.path != f"/employees/{guid}"
                    or self.headers.get("Authorization") != "Bearer e2e-service-token"
                ):
                    self.send_response(404)
                    self.end_headers()
                    return
                body = json.dumps(payload).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, _format, *args):
                return

        repository = ThreadingHTTPServer(("127.0.0.1", 0), RepositoryHandler)
        thread = threading.Thread(target=repository.serve_forever, daemon=True)
        thread.start()

        def stop_repository():
            repository.shutdown()
            repository.server_close()
            thread.join(timeout=2)

        self.addCleanup(stop_repository)
        repository_url = f"http://127.0.0.1:{repository.server_port}"

        sso = self._client()
        with override_settings(
            ACCOUNT_REPOSITORY_BACKEND="http",
            ACCOUNT_REPOSITORY_URL=repository_url,
            ACCOUNT_REPOSITORY_TOKEN="e2e-service-token",
            ACCOUNT_REPOSITORY_TIMEOUT=2,
        ):
            status, html = sso.post_without_csrf(
                "/accounts/token-login/", {"token": token}
            )
            self.assertEqual(status, 200)
            self.assertIn("Обращения граждан", html)
            status, _ = self._client().post_without_csrf(
                "/accounts/token-login/", {"token": token}
            )
            self.assertEqual(status, 403)

        synced = Employee.objects.get(guid=guid)
        self.assertEqual(synced.username, "external_e2e_user")
        self.assertEqual(synced.org, 81001)
        self.assertTrue(synced.groups.filter(name="СП1").exists())

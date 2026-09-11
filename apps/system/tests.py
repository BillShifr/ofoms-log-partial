"""Тесты общесистемных модулей (ТЗ разд. 3.2–3.8)."""

import base64
import datetime
import io
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
from unittest.mock import patch

from django.contrib import messages
from django.contrib.auth.models import Group
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import CommandError, call_command
from django.db import IntegrityError, connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.db.models import QuerySet
from django.test import Client, TestCase, TransactionTestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone
from openpyxl import load_workbook

from apps.core.models import EventLog, log_event
from apps.core.roles import ensure_role_groups
from apps.employee.models import Employee
from apps.journal.models import Irp, IrpTheme
from apps.journal.table import JOURNAL_TABLE_KEY
from apps.system.forms import ThreadForm
from apps.system.models import (
    Conversation,
    MessageAttachment,
    MessageReply,
    MessageThread,
    NewsCategory,
    NewsItem,
    SystemDocument,
    TaskAlreadyRunning,
    TaskDisabled,
    TaskFile,
    TaskJob,
    TaskNote,
    TaskRun,
    TaskRunSuperseded,
    UserTableViewPref,
)
from apps.system.validators import (
    ALLOWED_ATTACHMENT_EXTENSIONS,
    DOC_MAX_SIZE_BYTES,
    IMAGE_MAX_SIZE_BYTES,
    VIDEO_MAX_SIZE_BYTES,
    validate_attachment_file,
    validate_document_file,
)

SYS_MEDIA_ROOT = tempfile.mkdtemp(prefix="ejournal_system_media_")
PASSWORD = "GoodPass!1"


class BaseSystemTestCase(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        ensure_role_groups()

    def setUp(self):
        self.admin = Employee.objects.create_user(
            username="admin_sys", password=PASSWORD, org=81000, is_staff=True
        )
        admin_group = Group.objects.get(name="Администратор")
        self.admin.groups.add(admin_group)
        self.operator = Employee.objects.create_user(
            username="op_sys", password=PASSWORD, org=81000
        )
        self.operator.groups.add(Group.objects.get(name="ОП1"))
        self.smo = Employee.objects.create_user(
            username="smo_sys", password=PASSWORD, org=81001
        )
        self.smo.groups.add(Group.objects.get(name="СП1"))


class AccessTests(BaseSystemTestCase):
    def test_anonymous_redirected(self):
        for name in ("users", "events", "messages", "docs", "news", "prefs"):
            resp = self.client.get(reverse(f"system:{name}"))
            self.assertEqual(resp.status_code, 302, name)
            self.assertIn("/accounts/login", resp.url, name)

    def test_non_admin_denied_admin_screens(self):
        self.client.force_login(self.operator)
        for name in ("users", "user_create", "events", "tasks", "task_create"):
            resp = self.client.get(reverse(f"system:{name}"))
            self.assertEqual(resp.status_code, 403, name)
            self.assertContains(resp, "Недостаточно прав", status_code=403)

    def test_admin_can_open_admin_screens(self):
        self.admin.groups.add(Group.objects.get(name="ОП1"))
        self.client.force_login(self.admin)
        for name in ("users", "user_create", "events", "tasks", "task_create"):
            resp = self.client.get(reverse(f"system:{name}"))
            self.assertEqual(resp.status_code, 200, name)

    def test_admin_navigation_groups_management_destinations(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse("system:users"))

        self.assertContains(response, '<details class="nav__menu">')
        self.assertContains(response, ">Управление</summary>")
        self.assertContains(response, reverse("system:users"))
        self.assertContains(response, reverse("system:events"))
        self.assertContains(response, "/admin/")
        self.assertContains(response, "nav__menu-link--active")

    def test_user_screens_for_regular_user(self):
        self.client.force_login(self.operator)
        for name in ("messages", "docs", "news", "prefs"):
            resp = self.client.get(reverse(f"system:{name}"))
            self.assertEqual(resp.status_code, 200, name)


class UserManagementTests(BaseSystemTestCase):
    def test_create_user_with_role(self):
        self.client.force_login(self.admin)
        resp = self.client.post(
            reverse("system:user_create"),
            {
                "username": "new_user",
                "password1": PASSWORD,
                "password2": PASSWORD,
                "last_name": "Новаков",
                "org": "81001",
                "roles": [Group.objects.get(name="СП1").pk],
            },
        )
        self.assertEqual(resp.status_code, 302)
        user = Employee.objects.get(username="new_user")
        self.assertEqual(user.org, 81001)
        self.assertTrue(user.groups.filter(name="СП1").exists())
        self.assertTrue(
            EventLog.objects.filter(
                event_type=EventLog.EventType.CREATE, target__contains="new_user"
            ).exists()
        )

    def test_user_create_rolls_back_account_and_roles_when_audit_fails(self):
        self.client.force_login(self.admin)

        with (
            patch("apps.system.views.log_event", side_effect=RuntimeError("audit")),
            self.assertRaises(RuntimeError),
        ):
            self.client.post(
                reverse("system:user_create"),
                {
                    "username": "rollback_user",
                    "password1": PASSWORD,
                    "password2": PASSWORD,
                    "org": "81001",
                    "roles": [Group.objects.get(name="СП1").pk],
                },
            )

        self.assertFalse(Employee.objects.filter(username="rollback_user").exists())

    def test_update_user_roles(self):
        self.client.force_login(self.admin)
        user = Employee.objects.create_user(
            username="upd_user", password=PASSWORD, org=81000
        )
        resp = self.client.post(
            reverse("system:user_update", args=[user.pk]),
            {
                "last_name": "Иванов",
                "org": "81000",
                "roles": [Group.objects.get(name="ОП1").pk],
                "is_active": "on",
            },
        )
        self.assertEqual(resp.status_code, 302)
        user.refresh_from_db()
        self.assertTrue(user.groups.filter(name="ОП1").exists())

    def test_user_update_rolls_back_profile_and_roles_when_audit_fails(self):
        user = Employee.objects.create_user(
            username="rollback_update", password=PASSWORD, org=81000
        )
        self.client.force_login(self.admin)

        with (
            patch("apps.system.views.log_event", side_effect=RuntimeError("audit")),
            self.assertRaises(RuntimeError),
        ):
            self.client.post(
                reverse("system:user_update", args=[user.pk]),
                {
                    "last_name": "Не сохранится",
                    "org": "81000",
                    "roles": [Group.objects.get(name="ОП1").pk],
                    "is_active": "on",
                },
            )

        user.refresh_from_db()
        self.assertEqual(user.last_name, "")
        self.assertFalse(user.groups.exists())

    def test_role_must_match_selected_organization(self):
        self.client.force_login(self.admin)
        response = self.client.post(
            reverse("system:user_create"),
            {
                "username": "invalid_role_org",
                "password1": PASSWORD,
                "password2": PASSWORD,
                "org": "81001",
                "roles": [Group.objects.get(name="ОП1").pk],
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Роли не соответствуют выбранной организации")
        self.assertFalse(Employee.objects.filter(username="invalid_role_org").exists())

    def test_user_form_shows_server_capability_matrix(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse("system:user_create"))
        self.assertContains(response, "Матрица прав ролей")
        self.assertContains(response, "Регистрация обращений")
        self.assertContains(response, "СП3 — страховой представитель 3 уровня")

    def test_block_and_unblock(self):
        self.client.force_login(self.admin)
        user = Employee.objects.create_user(
            username="blocked", password=PASSWORD, org=81001
        )
        resp = self.client.post(reverse("system:user_block", args=[user.pk]))
        self.assertEqual(resp.status_code, 302)
        user.refresh_from_db()
        self.assertFalse(user.is_active)
        self.assertTrue(
            EventLog.objects.filter(
                event_type=EventLog.EventType.BLOCK, target__startswith=f"employee:{user.pk}"
            ).exists()
        )

    def test_block_rolls_back_when_audit_fails(self):
        user = Employee.objects.create_user(
            username="rollback_block", password=PASSWORD, org=81001
        )
        self.client.force_login(self.admin)

        with (
            patch("apps.system.views.log_event", side_effect=RuntimeError("audit")),
            self.assertRaises(RuntimeError),
        ):
            self.client.post(reverse("system:user_block", args=[user.pk]))

        user.refresh_from_db()
        self.assertTrue(user.is_active)

    def test_unblock_rolls_back_account_and_counter_when_audit_fails(self):
        user = Employee.objects.create_user(
            username="rollback_unblock",
            password=PASSWORD,
            org=81001,
            is_active=False,
            failed_attempts=7,
        )
        self.client.force_login(self.admin)

        with (
            patch("apps.system.views.log_event", side_effect=RuntimeError("audit")),
            self.assertRaises(RuntimeError),
        ):
            self.client.post(reverse("system:user_unblock", args=[user.pk]))

        user.refresh_from_db()
        self.assertFalse(user.is_active)
        self.assertEqual(user.failed_attempts, 7)
        resp = self.client.post(reverse("system:user_unblock", args=[user.pk]))
        self.assertEqual(resp.status_code, 302)
        user.refresh_from_db()
        self.assertTrue(user.is_active)
        self.assertEqual(user.failed_attempts, 0)
        self.assertTrue(
            EventLog.objects.filter(
                event_type=EventLog.EventType.UNBLOCK, user=self.admin
            ).exists()
        )

    def test_cannot_block_self(self):
        self.client.force_login(self.admin)
        resp = self.client.post(reverse("system:user_block", args=[self.admin.pk]))
        self.assertEqual(resp.status_code, 302)
        self.admin.refresh_from_db()
        self.assertTrue(self.admin.is_active)

    def test_cannot_deactivate_self_through_update_form(self):
        self.client.force_login(self.admin)
        admin_group = Group.objects.get(name="Администратор")
        response = self.client.post(
            reverse("system:user_update", args=[self.admin.pk]),
            {
                "last_name": self.admin.last_name,
                "org": str(self.admin.org),
                "roles": [admin_group.pk],
                "is_staff": "on",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Нельзя отключить собственную учётную запись")
        self.admin.refresh_from_db()
        self.assertTrue(self.admin.is_active)

    def test_cannot_remove_own_administrator_role_through_update_form(self):
        self.client.force_login(self.admin)
        operator_group = Group.objects.get(name="ОП1")
        response = self.client.post(
            reverse("system:user_update", args=[self.admin.pk]),
            {
                "last_name": self.admin.last_name,
                "org": str(self.admin.org),
                "roles": [operator_group.pk],
                "is_active": "on",
                "is_staff": "on",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Нельзя снять собственную роль администратора")
        self.admin.refresh_from_db()
        self.assertTrue(self.admin.groups.filter(name="Администратор").exists())

    def test_filter_by_org(self):
        self.client.force_login(self.admin)
        resp = self.client.get(reverse("system:users"), {"org": "81001"})
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, self.smo.username)
        self.assertNotContains(resp, self.operator.username)


class EventLogScreenTests(BaseSystemTestCase):
    def test_events_rendered_with_filters(self):
        log_event(module="journal", event_type=EventLog.EventType.CREATE, user=self.operator, target="irp:1")
        log_event(module="auth", event_type=EventLog.EventType.LOGIN, user=self.admin, result=EventLog.Result.FAILED, target="login:admin_sys")
        self.client.force_login(self.admin)
        resp = self.client.get(reverse("system:events"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "irp:1")
        event = EventLog.objects.filter(target="irp:1").get()
        self.assertContains(resp, f'data-sort-group="event-{event.pk}"', count=2)
        resp = self.client.get(
            reverse("system:events"), {"module": "auth", "result": "failed"}
        )
        self.assertContains(resp, "login:admin_sys")
        self.assertNotContains(resp, "irp:1")
        self.assertNotContains(resp, "Войти")  # фильтры работают

    def test_event_export_treats_user_controlled_cells_as_text(self):
        log_event(
            module="journal",
            event_type=EventLog.EventType.CREATE,
            user=self.operator,
            target='=HYPERLINK("https://example.invalid")',
        )
        self.client.force_login(self.admin)

        response = self.client.get(reverse("system:events_export"))
        workbook = load_workbook(io.BytesIO(response.content))
        target_cells = list(workbook.active["H"])[1:]

        self.assertEqual(response.status_code, 200)
        dangerous_cell = next(
            cell
            for cell in target_cells
            if cell.value == "'=HYPERLINK(\"https://example.invalid\")"
        )
        self.assertEqual(dangerous_cell.data_type, "s")

    def test_event_initiator_suggest_is_filtered_and_limited_in_database(self):
        for index in range(12):
            Employee.objects.create_user(
                username=f"audit_lookup_{index}",
                first_name="АЛЕКСАНДР",
                last_name=f"Проверка {index:02d}",
                org=81000,
            )
        self.client.force_login(self.admin)

        with CaptureQueriesContext(connection) as captured:
            response = self.client.get(
                reverse("system:event_initiator_suggest"), {"q": "александр"}
            )

        self.assertEqual(len(response.json()["suggestions"]), 10)
        employee_queries = [
            query["sql"].lower()
            for query in captured.captured_queries
            if "employee_employee" in query["sql"].lower()
        ]
        self.assertTrue(
            any("translate" in sql and "limit 10" in sql for sql in employee_queries)
        )


class MessageTests(BaseSystemTestCase):
    def _conv(self):
        conv = Conversation.objects.create(title="Обмен данными")
        conv.participants.set([self.operator, self.admin])
        return conv

    def test_create_conversation(self):
        self.client.force_login(self.operator)
        resp = self.client.post(
            reverse("system:conversation_create"),
            {"title": "Обмен данными", "participants": [str(self.admin.pk)]},
        )
        self.assertEqual(resp.status_code, 302)
        conv = Conversation.objects.get(title="Обмен данными")
        self.assertTrue(conv.participants.filter(pk=self.operator.pk).exists())
        self.assertTrue(conv.participants.filter(pk=self.admin.pk).exists())
        self.assertTrue(
            EventLog.objects.filter(event_type=EventLog.EventType.CREATE).exists()
        )

    def test_conversation_create_rolls_back_object_and_participants_on_audit_failure(self):
        self.client.force_login(self.operator)

        with (
            patch("apps.system.views.log_event", side_effect=RuntimeError("audit")),
            self.assertRaises(RuntimeError),
        ):
            self.client.post(
                reverse("system:conversation_create"),
                {"title": "Откат диалога", "participants": [str(self.admin.pk)]},
            )

        self.assertFalse(Conversation.objects.filter(title="Откат диалога").exists())

    def test_create_thread_records_author_and_audit(self):
        conv = self._conv()
        self.client.force_login(self.operator)

        response = self.client.post(
            reverse("system:thread_create", args=[conv.pk]),
            {"title": "Новая тема"},
        )

        self.assertEqual(response.status_code, 302)
        thread = MessageThread.objects.get(title="Новая тема")
        self.assertEqual(thread.created_by, self.operator)
        self.assertTrue(
            EventLog.objects.filter(
                event_type=EventLog.EventType.CREATE,
                user=self.operator,
                target=f"thread:{thread.pk}",
            ).exists()
        )

    def test_thread_create_rolls_back_on_audit_failure(self):
        conv = self._conv()
        self.client.force_login(self.operator)

        with (
            patch("apps.system.views.log_event", side_effect=RuntimeError("audit")),
            self.assertRaises(RuntimeError),
        ):
            self.client.post(
                reverse("system:thread_create", args=[conv.pk]),
                {"title": "Откат темы"},
            )

        self.assertFalse(MessageThread.objects.filter(title="Откат темы").exists())

    def test_conversation_list_query_count_does_not_grow_per_conversation(self):
        from django.test.utils import CaptureQueriesContext

        from apps.system.views import _conversations_meta

        for number in range(5):
            conv = Conversation.objects.create(title=f"Диалог {number}")
            conv.participants.set([self.operator, self.admin])
            thread = MessageThread.objects.create(
                conversation=conv, created_by=self.admin, title="Тема"
            )
            MessageReply.objects.create(
                thread=thread, author=self.admin, body=f"Сообщение {number}"
            )

        with CaptureQueriesContext(connection) as queries:
            meta = _conversations_meta(self.operator)
            list(meta)

        self.assertEqual(len(meta), 5)
        self.assertLessEqual(len(queries), 4)

    def test_conversation_search_matches_message_without_per_conversation_queries(self):
        conv = self._conv()
        thread = MessageThread.objects.create(
            conversation=conv, created_by=self.admin, title="Тема"
        )
        MessageReply.objects.create(
            thread=thread, author=self.admin, body="Уникальный текст обращения"
        )

        from apps.system.views import _conversations_meta

        meta = _conversations_meta(self.operator, "уникальный")

        self.assertEqual([item["conv"].pk for item in meta], [conv.pk])

    def test_conversation_without_participants_rejected(self):
        self.client.force_login(self.operator)
        resp = self.client.post(
            reverse("system:conversation_create"), {"title": "x"}
        )
        self.assertEqual(resp.status_code, 302)
        self.assertFalse(Conversation.objects.exists())

    def test_new_thread_cannot_be_created_closed(self):
        form = ThreadForm({"title": "Новая тема", "is_closed": "on"})

        self.assertTrue(form.is_valid())
        self.assertNotIn("is_closed", form.fields)
        self.assertFalse(form.save(commit=False).is_closed)

    def test_thread_author_can_close_and_reopen_topic(self):
        conv = self._conv()
        thread = MessageThread.objects.create(
            conversation=conv, created_by=self.operator, title="Управляемая тема"
        )
        self.client.force_login(self.operator)

        closed = self.client.post(reverse("system:thread_toggle", args=[thread.pk]))
        self.assertEqual(closed.status_code, 302)
        thread.refresh_from_db()
        self.assertTrue(thread.is_closed)
        self.assertTrue(
            EventLog.objects.filter(
                event_type=EventLog.EventType.UPDATE,
                user=self.operator,
                target=f"thread:{thread.pk}:closed",
            ).exists()
        )

        reopened = self.client.post(reverse("system:thread_toggle", args=[thread.pk]))
        self.assertEqual(reopened.status_code, 302)
        thread.refresh_from_db()
        self.assertFalse(thread.is_closed)

    def test_regular_participant_cannot_change_foreign_thread_state(self):
        conv = self._conv()
        thread = MessageThread.objects.create(
            conversation=conv, created_by=self.admin, title="Чужая тема"
        )
        self.client.force_login(self.operator)

        response = self.client.post(reverse("system:thread_toggle", args=[thread.pk]))

        self.assertEqual(response.status_code, 403)
        thread.refresh_from_db()
        self.assertFalse(thread.is_closed)
        self.assertFalse(
            EventLog.objects.filter(target__startswith=f"thread:{thread.pk}:").exists()
        )

    def test_admin_must_be_conversation_participant_to_manage_thread(self):
        conv = Conversation.objects.create(title="Закрытый диалог")
        conv.participants.set([self.operator, self.smo])
        thread = MessageThread.objects.create(
            conversation=conv, created_by=self.operator, title="Приватная тема"
        )
        self.client.force_login(self.admin)

        response = self.client.post(reverse("system:thread_toggle", args=[thread.pk]))

        self.assertEqual(response.status_code, 403)
        thread.refresh_from_db()
        self.assertFalse(thread.is_closed)

    def test_reply_to_thread_and_unread_badge(self):
        conv = self._conv()
        thread = MessageThread.objects.create(
            conversation=conv, created_by=self.admin, title="Ошибка ФЛК"
        )
        self.client.force_login(self.admin)
        resp = self.client.post(
            reverse("system:reply", args=[thread.pk]), {"body": "Посмотрите код 41"}
        )
        self.assertEqual(resp.status_code, 302)
        reply = MessageReply.objects.get(thread=thread)
        self.assertEqual(reply.author, self.admin)
        self.assertTrue(reply.is_new_for(self.operator))
        self.client.force_login(self.operator)
        resp = self.client.get(reverse("system:thread", args=[thread.pk]))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Посмотрите код 41")
        reply.refresh_from_db()
        self.assertFalse(reply.is_new_for(self.operator))

    def test_opening_conversation_preserves_unread_until_thread_is_opened(self):
        conv = self._conv()
        first = MessageThread.objects.create(
            conversation=conv, created_by=self.admin, title="Первая тема"
        )
        second = MessageThread.objects.create(
            conversation=conv, created_by=self.admin, title="Вторая тема"
        )
        first_reply = MessageReply.objects.create(
            thread=first, author=self.admin, body="Первое непрочитанное"
        )
        second_reply = MessageReply.objects.create(
            thread=second, author=self.admin, body="Второе непрочитанное"
        )
        self.client.force_login(self.operator)

        conversation = self.client.get(reverse("system:conversation", args=[conv.pk]))
        self.assertEqual(conversation.status_code, 200)
        self.assertContains(conversation, "непрочитанных: 2")
        self.assertTrue(first_reply.is_new_for(self.operator))
        self.assertTrue(second_reply.is_new_for(self.operator))

        self.client.get(reverse("system:thread", args=[first.pk]))
        first_reply.refresh_from_db()
        second_reply.refresh_from_db()
        self.assertFalse(first_reply.is_new_for(self.operator))
        self.assertTrue(second_reply.is_new_for(self.operator))

        conversation = self.client.get(reverse("system:conversation", args=[conv.pk]))
        self.assertContains(conversation, "непрочитанных: 1")

    def test_thread_reactions_toggle(self):
        conv = self._conv()
        thread = MessageThread.objects.create(
            conversation=conv, created_by=self.admin, title="Тема"
        )
        reply = MessageReply.objects.create(
            thread=thread, author=self.admin, body="Проверьте"
        )
        self.client.force_login(self.operator)
        resp = self.client.post(
            reverse("system:react", args=[reply.pk]), {"emoji": "👍"}
        )
        self.assertEqual(resp.status_code, 302)
        reply.refresh_from_db()
        self.assertIn(self.operator.pk, reply.reactions.get("👍", []))
        self.assertTrue(
            EventLog.objects.filter(
                event_type=EventLog.EventType.UPDATE,
                user=self.operator,
                target=f"reply:{reply.pk}:reaction:added",
                detail="👍",
            ).exists()
        )
        resp = self.client.post(
            reverse("system:react", args=[reply.pk]), {"emoji": "👍"}
        )
        self.assertEqual(resp.status_code, 302)
        reply.refresh_from_db()
        self.assertNotIn("👍", reply.reactions)
        self.assertTrue(
            EventLog.objects.filter(
                event_type=EventLog.EventType.UPDATE,
                user=self.operator,
                target=f"reply:{reply.pk}:reaction:removed",
                detail="👍",
            ).exists()
        )

    def test_reaction_rolls_back_when_semantic_audit_fails(self):
        conv = self._conv()
        thread = MessageThread.objects.create(
            conversation=conv, created_by=self.admin, title="Тема"
        )
        reply = MessageReply.objects.create(
            thread=thread, author=self.admin, body="Проверьте"
        )
        self.client.force_login(self.operator)

        with (
            patch("apps.system.views.log_event", side_effect=RuntimeError("audit")),
            self.assertRaises(RuntimeError),
        ):
            self.client.post(
                reverse("system:react", args=[reply.pk]), {"emoji": "👍"}
            )

        reply.refresh_from_db()
        self.assertEqual(reply.reactions, {})

    def test_foreign_user_forbidden_from_conversation(self):
        conv = self._conv()
        self.client.force_login(self.smo)
        resp = self.client.get(reverse("system:conversation", args=[conv.pk]))
        self.assertEqual(resp.status_code, 403)

    def test_thread_reply_with_attachment(self):
        conv = self._conv()
        thread = MessageThread.objects.create(
            conversation=conv, created_by=self.admin, title="Файлы"
        )
        self.client.force_login(self.operator)
        resp = self.client.post(
            reverse("system:reply", args=[thread.pk]),
            {
                "body": "Файл во вложении",
                "attachment": SimpleUploadedFile(
                    "reply-attach.pdf", b"%PDF-1.4", content_type="application/pdf"
                ),
            },
        )
        self.assertEqual(resp.status_code, 302)
        reply = MessageReply.objects.get(thread=thread)
        self.assertEqual(reply.attachments.count(), 1)

    def test_closed_thread_rejects_direct_reply_post_without_side_effects(self):
        conv = self._conv()
        thread = MessageThread.objects.create(
            conversation=conv,
            created_by=self.admin,
            title="Закрытая тема",
            is_closed=True,
        )
        self.client.force_login(self.operator)

        response = self.client.post(
            reverse("system:reply", args=[thread.pk]),
            {
                "body": "Сообщение в обход интерфейса",
                "attachment": SimpleUploadedFile("blocked.pdf", b"%PDF-1.4"),
            },
        )

        self.assertEqual(response.status_code, 403)
        self.assertFalse(thread.replies.exists())
        self.assertFalse(
            EventLog.objects.filter(
                event_type=EventLog.EventType.SEND,
                target__startswith=f"thread:{thread.pk}:reply:",
            ).exists()
        )

    def test_reply_rolls_back_when_semantic_audit_fails(self):
        conv = self._conv()
        thread = MessageThread.objects.create(
            conversation=conv, created_by=self.admin, title="Атомарная тема"
        )
        self.client.force_login(self.operator)

        with (
            patch("apps.system.views.log_event", side_effect=RuntimeError("audit")),
            self.assertRaises(RuntimeError),
        ):
            self.client.post(
                reverse("system:reply", args=[thread.pk]),
                {"body": "Не должно сохраниться"},
            )

        self.assertFalse(thread.replies.exists())

    def test_reply_rollback_removes_saved_attachment_from_storage(self):
        conv = self._conv()
        thread = MessageThread.objects.create(
            conversation=conv, created_by=self.admin, title="Атомарный файл"
        )
        self.client.force_login(self.operator)

        with tempfile.TemporaryDirectory() as media_root, override_settings(
            MEDIA_ROOT=media_root
        ):
            with (
                patch(
                    "apps.system.views.log_event",
                    side_effect=RuntimeError("audit"),
                ),
                self.assertRaises(RuntimeError),
            ):
                self.client.post(
                    reverse("system:reply", args=[thread.pk]),
                    {
                        "body": "Не должно сохраниться",
                        "attachment": SimpleUploadedFile(
                            "rollback.txt", b"private", content_type="text/plain"
                        ),
                    },
                )
            self.assertFalse(
                any(path.is_file() for path in Path(media_root).rglob("*"))
            )

        self.assertFalse(thread.replies.exists())

    def test_reply_unsafe_attachment_rejected(self):
        conv = self._conv()
        thread = MessageThread.objects.create(
            conversation=conv, created_by=self.admin, title="Файлы"
        )
        self.client.force_login(self.operator)
        resp = self.client.post(
            reverse("system:reply", args=[thread.pk]),
            {
                "body": "Вредоносный файл",
                "attachment": SimpleUploadedFile(
                    "evil.php", b"<?php", content_type="application/x-php"
                ),
            },
            follow=True,
        )
        self.assertEqual(resp.status_code, 200)
        reply = MessageReply.objects.get(thread=thread)
        self.assertEqual(reply.attachments.count(), 0)

    def test_participant_suggest_uses_database_and_excludes_inactive_users(self):
        active = Employee.objects.create_user(
            username="active_lookup", first_name="АЛЕКСАНДР", last_name="Поисков", org=81000
        )
        Employee.objects.create_user(
            username="inactive_lookup",
            first_name="АЛЕКСАНДР",
            last_name="Скрытый",
            org=81000,
            is_active=False,
        )
        self.client.force_login(self.operator)

        with CaptureQueriesContext(connection) as captured:
            response = self.client.get(
                reverse("system:users_suggest"), {"q": "александр"}
            )

        self.assertEqual(
            response.json()["suggestions"],
            [
                {
                    "id": active.pk,
                    "label": f"{active.full_name()} ({active.get_org_display()})",
                }
            ],
        )
        employee_queries = [
            query["sql"].lower()
            for query in captured.captured_queries
            if "employee_employee" in query["sql"].lower()
        ]
        self.assertTrue(any("translate" in sql and "limit 8" in sql for sql in employee_queries))

    def test_new_conversation_form_excludes_inactive_users(self):
        inactive = Employee.objects.create_user(
            username="inactive_participant", org=81000, is_active=False
        )
        self.client.force_login(self.operator)

        response = self.client.get(reverse("system:messages"))

        choices = response.context["form"].fields["participants"].queryset
        self.assertNotIn(inactive, choices)

        post_response = self.client.post(
            reverse("system:conversation_create"),
            {"title": "Недопустимый диалог", "participants": [inactive.pk]},
        )
        self.assertEqual(post_response.status_code, 302)
        self.assertFalse(Conversation.objects.filter(title="Недопустимый диалог").exists())

    def test_attachment_download_is_limited_to_conversation_participants(self):
        conv = self._conv()
        thread = MessageThread.objects.create(
            conversation=conv, created_by=self.admin, title="Закрытая тема"
        )
        reply = MessageReply.objects.create(thread=thread, author=self.admin, body="Файл")
        attachment = MessageAttachment.objects.create(
            reply=reply,
            file=SimpleUploadedFile("private.txt", b"private"),
            uploaded_by=self.admin,
        )
        self.client.force_login(self.smo)
        denied = self.client.get(
            reverse("system:message_attachment_download", args=[attachment.pk])
        )
        self.assertEqual(denied.status_code, 403)
        self.assertFalse(
            EventLog.objects.filter(target=f"message-attachment:{attachment.pk}").exists()
        )
        self.client.force_login(self.operator)
        allowed = self.client.get(
            reverse("system:message_attachment_download", args=[attachment.pk])
        )
        self.assertEqual(allowed.status_code, 200)
        self.assertEqual(b"".join(allowed.streaming_content), b"private")
        self.assertTrue(
            EventLog.objects.filter(
                event_type=EventLog.EventType.EXPORT,
                user=self.operator,
                target=f"message-attachment:{attachment.pk}",
            ).exists()
        )

    def test_database_rejects_message_attachment_without_reply(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            MessageAttachment.objects.create(
                reply=None,
                file=SimpleUploadedFile("orphan.txt", b"orphan"),
                uploaded_by=self.operator,
            )

    @override_settings(MEDIA_ROOT=SYS_MEDIA_ROOT)
    def test_deleting_conversation_removes_cascaded_attachment_file(self):
        conv = self._conv()
        thread = MessageThread.objects.create(
            conversation=conv, created_by=self.admin, title="Удаляемая тема"
        )
        reply = MessageReply.objects.create(thread=thread, author=self.admin, body="Файл")
        attachment = MessageAttachment.objects.create(
            reply=reply,
            file=SimpleUploadedFile("cascade-message.txt", b"message"),
            uploaded_by=self.admin,
        )
        storage = attachment.file.storage
        name = attachment.file.name
        self.assertTrue(storage.exists(name))

        with self.captureOnCommitCallbacks(execute=True):
            conv.delete()

        self.assertFalse(storage.exists(name))


@override_settings(MEDIA_ROOT=SYS_MEDIA_ROOT)
class DocTests(BaseSystemTestCase):
    def test_upload_document(self):
        self.client.force_login(self.admin)
        resp = self.client.post(
            reverse("system:doc_upload"),
            {
                "title": "Руководство пользователя",
                "sort_order": "1",
                "file": SimpleUploadedFile("manual.pdf", b"%PDF-1.4", content_type="application/pdf"),
            },
        )
        self.assertEqual(resp.status_code, 302)
        doc = SystemDocument.objects.get()
        self.assertEqual(doc.title, "Руководство пользователя")
        self.assertTrue(doc.file.name.endswith("manual.pdf"))

    def test_document_upload_rollback_removes_storage_object(self):
        self.client.force_login(self.admin)

        with tempfile.TemporaryDirectory() as media_root, override_settings(
            MEDIA_ROOT=media_root
        ):
            with (
                patch(
                    "apps.system.views.log_event",
                    side_effect=RuntimeError("audit"),
                ),
                self.assertRaises(RuntimeError),
            ):
                self.client.post(
                    reverse("system:doc_upload"),
                    {
                        "title": "Откат",
                        "sort_order": "0",
                        "file": SimpleUploadedFile("rollback.pdf", b"%PDF-1.4"),
                    },
                )
            self.assertFalse(
                any(path.is_file() for path in Path(media_root).rglob("*"))
            )

        self.assertFalse(SystemDocument.objects.filter(title="Откат").exists())

    def test_regular_user_sees_docs(self):
        SystemDocument.objects.create(
            title="Спецификация",
            file=SimpleUploadedFile("spec.pdf", b"%PDF-1.4", content_type="application/pdf"),
            uploaded_by=self.admin,
        )
        self.client.force_login(self.operator)
        resp = self.client.get(reverse("system:docs"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Спецификация")

    def test_regular_user_cannot_upload_or_delete(self):
        self.client.force_login(self.operator)
        resp = self.client.post(
            reverse("system:doc_upload"),
            {"title": "x", "file": SimpleUploadedFile("x.pdf", b"x")},
        )
        self.assertEqual(resp.status_code, 403)
        doc = SystemDocument.objects.create(
            title="del", file=SimpleUploadedFile("d.pdf", b"x"), uploaded_by=self.admin
        )
        resp = self.client.post(reverse("system:doc_delete", args=[doc.pk]))
        self.assertEqual(resp.status_code, 403)

    def test_deleting_document_removes_stored_file_after_commit(self):
        doc = SystemDocument.objects.create(
            title="Удаляемый документ",
            file=SimpleUploadedFile("delete-me.pdf", b"%PDF-1.4"),
            uploaded_by=self.admin,
        )
        storage = doc.file.storage
        name = doc.file.name
        self.assertTrue(storage.exists(name))
        self.client.force_login(self.admin)

        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(reverse("system:doc_delete", args=[doc.pk]))

        self.assertEqual(response.status_code, 302)
        self.assertFalse(storage.exists(name))

    def test_document_delete_failure_rolls_back_semantic_audit(self):
        doc = SystemDocument.objects.create(
            title="Неудалённый документ",
            file=SimpleUploadedFile("kept.pdf", b"%PDF-1.4"),
            uploaded_by=self.admin,
        )
        target = f"doc:{doc.pk}:{doc.title}"
        self.client.force_login(self.admin)

        with (
            patch.object(SystemDocument, "delete", side_effect=RuntimeError("delete")),
            self.assertRaises(RuntimeError),
        ):
            self.client.post(reverse("system:doc_delete", args=[doc.pk]))

        self.assertTrue(SystemDocument.objects.filter(pk=doc.pk).exists())
        self.assertFalse(
            EventLog.objects.filter(
                event_type=EventLog.EventType.DELETE, target=target
            ).exists()
        )

    def test_doc_download_increments_counter(self):
        doc = SystemDocument.objects.create(
            title="Руководство",
            file=SimpleUploadedFile("download-check.pdf", b"%PDF-1.4", content_type="application/pdf"),
            uploaded_by=self.admin,
        )
        self.client.force_login(self.operator)
        resp = self.client.get(reverse("system:doc_download", args=[doc.pk]))
        self.assertEqual(resp.status_code, 200)
        doc.refresh_from_db()
        self.assertEqual(doc.downloads_count, 1)
        self.assertTrue(
            EventLog.objects.filter(
                event_type=EventLog.EventType.EXPORT,
                user=self.operator,
                target=f"doc:{doc.pk}:{doc.title}",
            ).exists()
        )

    def test_unavailable_document_is_not_counted_or_audited_as_downloaded(self):
        doc = SystemDocument.objects.create(
            title="Недоступный файл",
            file=SimpleUploadedFile("missing.pdf", b"missing"),
            uploaded_by=self.admin,
        )
        self.client.force_login(self.operator)

        with patch.object(doc.file.storage, "open", side_effect=OSError("offline")):
            response = self.client.get(reverse("system:doc_download", args=[doc.pk]))

        self.assertEqual(response.status_code, 404)
        doc.refresh_from_db()
        self.assertEqual(doc.downloads_count, 0)
        self.assertFalse(
            EventLog.objects.filter(target=f"doc:{doc.pk}:{doc.title}").exists()
        )

    def test_document_download_counter_rolls_back_when_audit_fails(self):
        doc = SystemDocument.objects.create(
            title="Документ без ложного счётчика",
            file=SimpleUploadedFile("audit-failure.pdf", b"%PDF-1.4"),
            uploaded_by=self.admin,
        )
        self.client.force_login(self.operator)
        file_handle = io.BytesIO(b"%PDF-1.4")

        with (
            patch(
                "apps.system.views.open_field_file_or_404",
                return_value=file_handle,
            ),
            patch("apps.system.views.log_event", side_effect=RuntimeError("audit")),
            self.assertRaises(RuntimeError),
        ):
            self.client.get(reverse("system:doc_download", args=[doc.pk]))

        self.assertTrue(file_handle.closed)
        doc.refresh_from_db()
        self.assertEqual(doc.downloads_count, 0)
        self.assertFalse(
            EventLog.objects.filter(target=f"doc:{doc.pk}:{doc.title}").exists()
        )

    def test_video_can_be_viewed_inline_by_authenticated_user(self):
        doc = SystemDocument.objects.create(
            title="Обучение",
            file=SimpleUploadedFile("training.mp4", b"video", content_type="video/mp4"),
            file_type="mp4",
            uploaded_by=self.admin,
        )
        self.client.force_login(self.operator)
        resp = self.client.get(reverse("system:doc_view", args=[doc.pk]))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp["Content-Type"], "video/mp4")
        self.assertTrue(resp["Content-Disposition"].startswith("inline;"))
        self.assertTrue(
            EventLog.objects.filter(
                event_type=EventLog.EventType.VIEW,
                user=self.operator,
                target=f"doc:{doc.pk}:view",
            ).exists()
        )

    def test_video_view_requires_authentication(self):
        doc = SystemDocument.objects.create(
            title="Обучение",
            file=SimpleUploadedFile("private.mp4", b"video", content_type="video/mp4"),
            file_type="mp4",
            uploaded_by=self.admin,
        )
        resp = self.client.get(reverse("system:doc_view", args=[doc.pk]))
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/login/", resp.url)

    def test_non_video_cannot_be_opened_in_video_view(self):
        doc = SystemDocument.objects.create(
            title="Инструкция",
            file=SimpleUploadedFile(
                "view-denied.pdf", b"%PDF-1.4", content_type="application/pdf"
            ),
            file_type="pdf",
            uploaded_by=self.admin,
        )
        self.client.force_login(self.operator)
        resp = self.client.get(reverse("system:doc_view", args=[doc.pk]))
        self.assertEqual(resp.status_code, 404)

    def test_video_card_has_separate_view_action(self):
        SystemDocument.objects.create(
            title="Обучение",
            file=SimpleUploadedFile("card.mp4", b"video", content_type="video/mp4"),
            file_type="mp4",
            uploaded_by=self.admin,
        )
        self.client.force_login(self.operator)
        resp = self.client.get(reverse("system:docs"))
        self.assertContains(resp, "Смотреть")
        self.assertContains(resp, reverse("system:doc_view", args=[SystemDocument.objects.get().pk]))

    def test_doc_suggest(self):
        SystemDocument.objects.create(
            title="Инструкция оператора",
            file=SimpleUploadedFile("suggest-check.pdf", b"%PDF-1.4", content_type="application/pdf"),
            uploaded_by=self.admin,
        )
        self.client.force_login(self.operator)
        resp = self.client.get(reverse("system:doc_suggest"), {"q": "инст"})
        self.assertEqual(resp.status_code, 200)
        self.assertIn("Инструкция оператора", resp.json()["suggestions"])
        short = self.client.get(reverse("system:doc_suggest"), {"q": "ин"})
        self.assertEqual(short.json()["suggestions"], [])

    def test_document_search_runs_in_database_and_folds_cyrillic(self):
        SystemDocument.objects.create(
            title="Регламент оператора",
            description="ПРОВЕРКА ДОСТУПНОСТИ",
            file=SimpleUploadedFile("database-search.pdf", b"%PDF-1.4"),
            uploaded_by=self.admin,
        )
        self.client.force_login(self.operator)

        with CaptureQueriesContext(connection) as captured:
            response = self.client.get(reverse("system:docs"), {"q": "проверка"})

        self.assertContains(response, "Регламент оператора")
        document_queries = [
            query["sql"].lower()
            for query in captured.captured_queries
            if "system_systemdocument" in query["sql"].lower()
        ]
        self.assertTrue(any("translate" in sql for sql in document_queries))


class NewsTests(BaseSystemTestCase):
    def test_news_visible_for_users(self):
        NewsItem.objects.create(title="Обновление системы", text="Текст", author=self.admin, is_active=True)
        self.client.force_login(self.smo)
        resp = self.client.get(reverse("system:news"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Обновление системы")

    def test_oversized_cover_is_rejected(self):
        self.client.force_login(self.admin)
        oversized = SimpleUploadedFile(
            "cover.png",
            b"x" * (IMAGE_MAX_SIZE_BYTES + 1),
            content_type="image/png",
        )

        response = self.client.post(
            reverse("system:news_create"),
            {"title": "Большая обложка", "text": "Текст", "cover_image": oversized},
        )

        self.assertEqual(response.status_code, 302)
        self.assertFalse(NewsItem.objects.filter(title="Большая обложка").exists())

    def test_news_create_rollback_removes_cover_from_storage(self):
        self.client.force_login(self.admin)

        with tempfile.TemporaryDirectory() as media_root, override_settings(
            MEDIA_ROOT=media_root
        ):
            with (
                patch(
                    "apps.system.views.log_event",
                    side_effect=RuntimeError("audit"),
                ),
                self.assertRaises(RuntimeError),
            ):
                self.client.post(
                    reverse("system:news_create"),
                    {
                        "title": "Откат обложки",
                        "text": "Текст",
                        "cover_image": SimpleUploadedFile(
                            "rollback.png",
                            base64.b64decode(
                                "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwC"
                                "AAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
                            ),
                            content_type="image/png",
                        ),
                    },
                )
            self.assertFalse(
                any(path.is_file() for path in Path(media_root).rglob("*"))
            )

        self.assertFalse(NewsItem.objects.filter(title="Откат обложки").exists())

    def test_news_update_rollback_preserves_old_cover_and_removes_new_one(self):
        with tempfile.TemporaryDirectory() as media_root, override_settings(
            MEDIA_ROOT=media_root
        ):
            item = NewsItem.objects.create(
                title="Исходная новость",
                text="Исходный текст",
                author=self.admin,
                cover_image=SimpleUploadedFile("old.png", b"old"),
            )
            old_name = item.cover_image.name
            self.client.force_login(self.admin)

            with (
                patch(
                    "apps.system.views.log_event",
                    side_effect=RuntimeError("audit"),
                ),
                self.assertRaises(RuntimeError),
            ):
                self.client.post(
                    reverse("system:news_update", args=[item.pk]),
                    {
                        "title": "Изменённая новость",
                        "text": "Изменённый текст",
                        "cover_image": SimpleUploadedFile(
                            "new.png",
                            base64.b64decode(
                                "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwC"
                                "AAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
                            ),
                            content_type="image/png",
                        ),
                    },
                )

            item.refresh_from_db()
            self.assertEqual(item.title, "Исходная новость")
            self.assertEqual(item.cover_image.name, old_name)
            stored_files = [
                path.relative_to(media_root).as_posix()
                for path in Path(media_root).rglob("*")
                if path.is_file()
            ]
            self.assertEqual(stored_files, [old_name])

    def test_hidden_news_not_for_regular_user(self):
        NewsItem.objects.create(title="Черновик", text="x", author=self.admin, is_active=False)
        self.client.force_login(self.smo)
        resp = self.client.get(reverse("system:news"))
        self.assertNotContains(resp, "Черновик")

    def test_admin_create_and_toggle(self):
        self.client.force_login(self.admin)
        resp = self.client.post(
            reverse("system:news_create"),
            {"title": "Плановый простой", "text": "00:00-02:00", "summary": "Остановка", "is_active": "on"},
        )
        self.assertEqual(resp.status_code, 302)
        item = NewsItem.objects.get()
        self.assertTrue(item.is_active)
        self.assertTrue(item.slug)
        self.assertEqual(item.author, self.admin)
        resp = self.client.post(reverse("system:news_toggle", args=[item.pk]))
        self.assertEqual(resp.status_code, 302)
        item.refresh_from_db()
        self.assertFalse(item.is_active)
        self.assertTrue(
            EventLog.objects.filter(
                event_type=EventLog.EventType.UPDATE,
                user=self.admin,
                target=f"news:{item.pk}:hidden",
            ).exists()
        )

    def test_news_toggle_rolls_back_when_semantic_audit_fails(self):
        item = NewsItem.objects.create(
            title="Публикация", text="Текст", author=self.admin, is_active=True
        )
        self.client.force_login(self.admin)

        with (
            patch("apps.system.views.log_event", side_effect=RuntimeError("audit")),
            self.assertRaises(RuntimeError),
        ):
            self.client.post(reverse("system:news_toggle", args=[item.pk]))

        item.refresh_from_db()
        self.assertTrue(item.is_active)

    def test_non_admin_cannot_create(self):
        self.client.force_login(self.operator)
        resp = self.client.post(reverse("system:news_create"), {"title": "x"})
        self.assertEqual(resp.status_code, 403)

    @override_settings(MEDIA_ROOT=SYS_MEDIA_ROOT)
    def test_deleting_news_removes_cover_after_commit(self):
        item = NewsItem.objects.create(
            title="Удаляемая новость",
            text="Текст",
            author=self.admin,
            cover_image=SimpleUploadedFile("delete-cover.png", b"image"),
        )
        storage = item.cover_image.storage
        name = item.cover_image.name
        self.assertTrue(storage.exists(name))
        self.client.force_login(self.admin)

        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(reverse("system:news_delete", args=[item.pk]))

        self.assertEqual(response.status_code, 302)
        self.assertFalse(storage.exists(name))

    def test_news_delete_failure_rolls_back_semantic_audit(self):
        item = NewsItem.objects.create(
            title="Неудалённая новость", text="Текст", author=self.admin
        )
        target = f"news:{item.pk}"
        self.client.force_login(self.admin)

        with (
            patch.object(NewsItem, "delete", side_effect=RuntimeError("delete")),
            self.assertRaises(RuntimeError),
        ):
            self.client.post(reverse("system:news_delete", args=[item.pk]))

        self.assertTrue(NewsItem.objects.filter(pk=item.pk).exists())
        self.assertFalse(
            EventLog.objects.filter(
                event_type=EventLog.EventType.DELETE, target=target
            ).exists()
        )

    @override_settings(MEDIA_ROOT=SYS_MEDIA_ROOT)
    def test_replacing_news_cover_removes_previous_file_after_commit(self):
        item = NewsItem.objects.create(
            title="Новость с заменяемой обложкой",
            author=self.admin,
            cover_image=SimpleUploadedFile("old-cover.png", b"old"),
        )
        storage = item.cover_image.storage
        old_name = item.cover_image.name
        self.assertTrue(storage.exists(old_name))

        item.cover_image = SimpleUploadedFile("new-cover.png", b"new")
        with self.captureOnCommitCallbacks(execute=True):
            item.save()

        self.assertFalse(storage.exists(old_name))
        self.assertTrue(storage.exists(item.cover_image.name))
        self.assertEqual(item.cover_image.read(), b"new")

    def test_detail_increments_views(self):
        item = NewsItem.objects.create(
            title="Сводка", text="<b>текст</b>", author=self.admin, is_active=True
        )
        self.client.force_login(self.smo)
        resp = self.client.get(reverse("system:news_detail", args=[item.pk]))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "текст")
        item.refresh_from_db()
        self.assertEqual(item.views_count, 1)

    def test_hidden_news_not_shown_to_regular_user(self):
        item = NewsItem.objects.create(title="Секрет", author=self.admin, is_active=False)
        self.client.force_login(self.smo)
        resp = self.client.get(reverse("system:news_detail", args=[item.pk]))
        self.assertEqual(resp.status_code, 404)

    @override_settings(MEDIA_ROOT=SYS_MEDIA_ROOT)
    def test_cover_uses_protected_endpoint(self):
        item = NewsItem.objects.create(
            title="Новость с обложкой",
            text="Текст",
            author=self.admin,
            is_active=True,
            cover_image=SimpleUploadedFile(
                "protected-cover.png",
                b"image-content",
                content_type="image/png",
            ),
        )
        cover_url = reverse("system:news_cover", args=[item.pk])

        self.client.force_login(self.smo)
        list_response = self.client.get(reverse("system:news"))
        detail_response = self.client.get(reverse("system:news_detail", args=[item.pk]))
        cover_response = self.client.get(cover_url)

        self.assertContains(list_response, f'src="{cover_url}"')
        self.assertContains(detail_response, f'src="{cover_url}"')
        self.assertNotContains(list_response, item.cover_image.url)
        self.assertEqual(cover_response.status_code, 200)
        self.assertEqual(cover_response["Content-Type"], "image/png")
        self.assertEqual(b"".join(cover_response.streaming_content), b"image-content")

    @override_settings(MEDIA_ROOT=SYS_MEDIA_ROOT)
    def test_cover_requires_login_and_respects_publication_status(self):
        item = NewsItem.objects.create(
            title="Скрытая обложка",
            author=self.admin,
            is_active=False,
            cover_image=SimpleUploadedFile("hidden.png", b"hidden-image"),
        )
        cover_url = reverse("system:news_cover", args=[item.pk])

        anonymous_response = self.client.get(cover_url)
        self.assertEqual(anonymous_response.status_code, 302)

        self.client.force_login(self.smo)
        self.assertEqual(self.client.get(cover_url).status_code, 404)

        self.client.force_login(self.admin)
        admin_response = self.client.get(cover_url)
        self.assertEqual(admin_response.status_code, 200)
        self.assertEqual(b"".join(admin_response.streaming_content), b"hidden-image")

    def test_rich_text_rejects_script_and_protocol_relative_links(self):
        item = NewsItem.objects.create(
            title="Безопасная разметка",
            text=(
                '<script>alert(1)</script><a href="javascript:alert(2)">bad</a>'
                '<a href="//evil.example/path">external</a>'
                '<a href="/system/news/">local</a>'
            ),
            author=self.admin,
            is_active=True,
        )
        self.client.force_login(self.operator)

        response = self.client.get(reverse("system:news_detail", args=[item.pk]))
        body = response.content.decode()

        self.assertNotIn("<script>alert(1)", body)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", body)
        self.assertNotIn('href="javascript:', body)
        self.assertNotIn('href="//evil.example', body)
        self.assertIn('href="/system/news/"', body)

    def test_news_suggest(self):
        NewsItem.objects.create(title="Изменение регламента", author=self.admin)
        self.client.force_login(self.smo)
        resp = self.client.get(reverse("system:news_suggest"), {"q": "изм"})
        self.assertEqual(resp.status_code, 200)
        self.assertIn("Изменение регламента", resp.json()["suggestions"])

    def test_news_search_runs_in_database_and_folds_cyrillic(self):
        NewsItem.objects.create(
            title="Служебное объявление",
            summary="ПЛАНОВЫЕ РАБОТЫ",
            author=self.admin,
            is_active=True,
        )
        self.client.force_login(self.smo)

        with CaptureQueriesContext(connection) as captured:
            response = self.client.get(reverse("system:news"), {"q": "плановые"})

        self.assertContains(response, "Служебное объявление")
        news_queries = [
            query["sql"].lower()
            for query in captured.captured_queries
            if "system_newsitem" in query["sql"].lower()
        ]
        self.assertTrue(any("translate" in sql for sql in news_queries))

    def test_category_seed_and_filter(self):
        cat = NewsCategory.objects.create(name="Эксплуатация", slug="operations")
        NewsItem.objects.create(title="Регламент", author=self.admin, category=cat, is_active=True)
        self.client.force_login(self.smo)
        resp = self.client.get(reverse("system:news"), {"category": "operations"})
        self.assertContains(resp, "Регламент")
        resp = self.client.get(reverse("system:news"), {"category": "other"})
        self.assertNotContains(resp, "Регламент")


class TaskTests(BaseSystemTestCase):
    def _make_task(self, **kw):
        defaults = {
            "name": "Проверка", "command": "noop", "run_mode": TaskJob.RunMode.MANUAL, "enabled": True,
            "created_by": self.admin,
        }
        defaults.update(kw)
        return TaskJob.objects.create(**defaults)

    def test_create_task(self):
        self.client.force_login(self.admin)
        resp = self.client.post(
            reverse("system:task_create"),
            {"name": "Импорт", "command": "exchange_import", "run_mode": "manual",
             "description": "Автозагрузка", "enabled": "on"},
        )
        self.assertEqual(resp.status_code, 302)
        task = TaskJob.objects.get(name="Импорт")
        self.assertEqual(task.created_by, self.admin)

    def test_task_create_rolls_back_when_audit_fails(self):
        self.client.force_login(self.admin)

        with (
            patch("apps.system.views.log_event", side_effect=RuntimeError("audit")),
            self.assertRaises(RuntimeError),
        ):
            self.client.post(
                reverse("system:task_create"),
                {
                    "name": "Откат создания задачи",
                    "command": "noop",
                    "run_mode": TaskJob.RunMode.MANUAL,
                    "enabled": "on",
                },
            )

        self.assertFalse(
            TaskJob.objects.filter(name="Откат создания задачи").exists()
        )

    def test_task_update_rolls_back_when_audit_fails(self):
        task = self._make_task(name="Исходная задача")
        self.client.force_login(self.admin)

        with (
            patch("apps.system.views.log_event", side_effect=RuntimeError("audit")),
            self.assertRaises(RuntimeError),
        ):
            self.client.post(
                reverse("system:task_update", args=[task.pk]),
                {
                    "name": "Не сохранится",
                    "command": task.command,
                    "run_mode": TaskJob.RunMode.MANUAL,
                    "priority": TaskJob.Priority.HIGH,
                    "enabled": "on",
                },
            )

        task.refresh_from_db()
        self.assertEqual(task.name, "Исходная задача")
        self.assertEqual(task.priority, TaskJob.Priority.LOW)

    def test_task_note_rolls_back_when_audit_fails(self):
        task = self._make_task()
        self.client.force_login(self.admin)

        with (
            patch("apps.system.views.log_event", side_effect=RuntimeError("audit")),
            self.assertRaises(RuntimeError),
        ):
            self.client.post(
                reverse("system:task_update", args=[task.pk]),
                {"action": "note", "text": "Не сохранится"},
            )

        self.assertFalse(task.notes.exists())

    def test_task_note_create_audit_contains_note_identity(self):
        task = self._make_task()
        self.client.force_login(self.admin)

        response = self.client.post(
            reverse("system:task_update", args=[task.pk]),
            {"action": "note", "text": "Идентифицируемая заметка"},
        )

        self.assertEqual(response.status_code, 302)
        note = task.notes.get()
        self.assertTrue(
            EventLog.objects.filter(
                event_type=EventLog.EventType.UPDATE,
                user=self.admin,
                target=f"task:{task.pk}:note:{note.pk}",
            ).exists()
        )

    def test_task_note_delete_rolls_back_when_audit_fails(self):
        task = self._make_task()
        note = TaskNote.objects.create(
            task=task, author=self.admin, text="Останется после отката"
        )
        self.client.force_login(self.admin)

        with (
            patch("apps.system.views.log_event", side_effect=RuntimeError("audit")),
            self.assertRaises(RuntimeError),
        ):
            self.client.post(
                reverse("system:task_update", args=[task.pk]),
                {"action": "note_delete", "note_id": note.pk},
            )

        note.refresh_from_db()
        self.assertEqual(note.text, "Останется после отката")

    def test_task_status_cannot_be_forged_through_form(self):
        self.client.force_login(self.admin)

        response = self.client.post(
            reverse("system:task_create"),
            {
                "name": "Подмена статуса",
                "command": "noop",
                "status": TaskJob.Status.RUNNING,
                "run_mode": TaskJob.RunMode.MANUAL,
                "enabled": "on",
            },
        )

        self.assertEqual(response.status_code, 302)
        task = TaskJob.objects.get(name="Подмена статуса")
        self.assertEqual(task.status, TaskJob.Status.CREATED)
        self.assertIsNone(task.last_started_at)

    def test_task_command_must_come_from_registry(self):
        self.client.force_login(self.admin)

        response = self.client.post(
            reverse("system:task_create"),
            {
                "name": "Неизвестная команда",
                "command": "shell_arbitrary",
                "run_mode": TaskJob.RunMode.MANUAL,
                "enabled": "on",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Выберите корректный вариант")
        self.assertContains(response, '<select name="command"')
        self.assertFalse(TaskJob.objects.filter(name="Неизвестная команда").exists())

    def test_manual_mode_clears_stale_interval(self):
        task = self._make_task(
            run_mode=TaskJob.RunMode.SCHEDULED,
            interval_minutes=15,
        )
        self.client.force_login(self.admin)

        response = self.client.post(
            reverse("system:task_update", args=[task.pk]),
            {
                "name": task.name,
                "command": task.command,
                "status": TaskJob.Status.RUNNING,
                "run_mode": TaskJob.RunMode.MANUAL,
                "priority": TaskJob.Priority.LOW,
                "enabled": "on",
            },
        )

        self.assertEqual(response.status_code, 302)
        task.refresh_from_db()
        self.assertEqual(task.status, TaskJob.Status.CREATED)
        self.assertIsNone(task.interval_minutes)

    def test_inactive_employee_cannot_be_newly_assigned(self):
        inactive = Employee.objects.create_user(
            username="inactive_task_assignment",
            password=PASSWORD,
            org=81000,
            is_active=False,
        )
        self.client.force_login(self.admin)

        response = self.client.post(
            reverse("system:task_create"),
            {
                "name": "Недопустимый исполнитель",
                "command": "noop",
                "assigned_to": inactive.pk,
                "run_mode": TaskJob.RunMode.MANUAL,
                "enabled": "on",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Выберите корректный вариант")
        self.assertContains(response, 'data-key="task-form-sched" open')
        self.assertFalse(TaskJob.objects.filter(name="Недопустимый исполнитель").exists())

    def test_manual_run(self):
        self.client.force_login(self.admin)
        task = self._make_task()
        resp = self.client.post(reverse("system:task_run", args=[task.pk]))
        self.assertEqual(resp.status_code, 302)
        task.refresh_from_db()
        self.assertEqual(task.last_result, EventLog.Result.OK)
        run = TaskRun.objects.get(task=task)
        self.assertEqual(run.triggered_by, "user")
        self.assertEqual(run.result, EventLog.Result.OK)
        self.assertTrue(
            EventLog.objects.filter(event_type=EventLog.EventType.TASK, target=f"task:{task.pk}:noop").exists()
        )

    def test_task_and_log_rows_share_sort_group(self):
        task = self._make_task(last_log="Последний лог")
        self.client.force_login(self.admin)
        response = self.client.get(reverse("system:tasks"))
        self.assertContains(response, f'data-sort-group="task-{task.pk}"', count=2)
        self.assertContains(response, "data-no-sort")

    def test_running_task_cannot_be_started_twice(self):
        task = self._make_task(
            status=TaskJob.Status.RUNNING,
            last_started_at=timezone.now(),
        )
        with self.assertRaises(TaskAlreadyRunning):
            task.run(user=self.admin)
        self.assertFalse(TaskRun.objects.exists())

        self.client.force_login(self.admin)
        response = self.client.post(
            reverse("system:task_run", args=[task.pk]), follow=True
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "уже выполняется")
        self.assertFalse(TaskRun.objects.exists())

    def test_disabled_task_cannot_be_started_through_model_or_portal(self):
        task = self._make_task(enabled=False)

        with self.assertRaises(TaskDisabled):
            task.run(user=self.admin)

        task.refresh_from_db()
        self.assertEqual(task.status, TaskJob.Status.CREATED)
        self.assertFalse(TaskRun.objects.exists())
        self.assertFalse(
            EventLog.objects.filter(event_type=EventLog.EventType.TASK).exists()
        )

        self.client.force_login(self.admin)
        response = self.client.post(
            reverse("system:task_run", args=[task.pk]), follow=True
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "отключено")
        self.assertFalse(TaskRun.objects.exists())

        card = self.client.get(reverse("system:task_update", args=[task.pk]))
        self.assertContains(card, 'disabled title="Сначала включите задание"')

    def test_cancelled_task_cannot_be_enabled_without_state_reset(self):
        task = self._make_task(enabled=False, status=TaskJob.Status.CANCELLED)

        with self.assertRaises(IntegrityError), transaction.atomic():
            TaskJob.objects.filter(pk=task.pk).update(enabled=True)

        self.client.force_login(self.admin)
        response = self.client.post(reverse("system:task_toggle", args=[task.pk]))

        self.assertEqual(response.status_code, 302)
        task.refresh_from_db()
        self.assertTrue(task.enabled)
        self.assertEqual(task.status, TaskJob.Status.CREATED)

    def test_saving_cancelled_task_as_enabled_resets_state(self):
        task = self._make_task(enabled=False, status=TaskJob.Status.CANCELLED)
        self.client.force_login(self.admin)

        response = self.client.post(
            reverse("system:task_update", args=[task.pk]),
            {
                "name": task.name,
                "command": task.command,
                "run_mode": TaskJob.RunMode.MANUAL,
                "priority": TaskJob.Priority.LOW,
                "enabled": "on",
            },
        )

        self.assertEqual(response.status_code, 302)
        task.refresh_from_db()
        self.assertTrue(task.enabled)
        self.assertEqual(task.status, TaskJob.Status.CREATED)

    def test_task_claim_rolls_back_when_pending_audit_fails(self):
        task = self._make_task()

        with (
            patch("apps.core.models.log_event", side_effect=RuntimeError("audit")),
            self.assertRaises(RuntimeError),
        ):
            task.run(user=self.admin)

        task.refresh_from_db()
        self.assertEqual(task.status, TaskJob.Status.CREATED)
        self.assertIsNone(task.last_started_at)
        self.assertFalse(TaskRun.objects.filter(task=task).exists())

    def test_task_completion_rolls_back_to_recoverable_pending_state(self):
        task = self._make_task()

        def fail_completion_event(*args, **kwargs):
            if kwargs.get("obj") is not None:
                raise RuntimeError("audit")
            return log_event(*args, **kwargs)

        with (
            patch("apps.core.models.log_event", side_effect=fail_completion_event),
            self.assertRaises(RuntimeError),
        ):
            task.run(user=self.admin)

        task.refresh_from_db()
        run = TaskRun.objects.get(task=task)
        event = EventLog.objects.get(
            event_type=EventLog.EventType.TASK,
            target=f"task:{task.pk}:{task.command}",
        )
        self.assertEqual(task.status, TaskJob.Status.RUNNING)
        self.assertIsNone(task.last_finished_at)
        self.assertEqual(run.result, "")
        self.assertIsNone(run.finished_at)
        self.assertIsNone(event.finished_at)

    def test_late_worker_cannot_overwrite_stale_recovery_result(self):
        task = self._make_task()

        def recover_while_command_is_running(*args, **kwargs):
            task.refresh_from_db()
            recovered_at = task.last_started_at + datetime.timedelta(seconds=2)
            with patch("apps.system.models.timezone.now", return_value=recovered_at):
                self.assertEqual(TaskJob.recover_stale(stale_after_seconds=1), 1)
            return "Поздний успешный результат"

        with (
            patch(
                "apps.system.tasks.run_command",
                side_effect=recover_while_command_is_running,
            ),
            self.assertRaises(TaskRunSuperseded),
        ):
            task.run()

        task.refresh_from_db()
        run = TaskRun.objects.get(task=task)
        event = EventLog.objects.get(
            event_type=EventLog.EventType.TASK,
            target=f"task:{task.pk}:{task.command}",
        )
        self.assertEqual(task.status, TaskJob.Status.FAILED)
        self.assertEqual(task.last_result, EventLog.Result.FAILED)
        self.assertEqual(run.result, EventLog.Result.FAILED)
        self.assertEqual(event.result, EventLog.Result.FAILED)
        self.assertIn("таймаута", task.last_log)

    def test_failed_command_logged(self):
        task = self._make_task()
        with patch("apps.system.tasks.run_command", side_effect=RuntimeError("boom")):
            run = task.run()
        self.assertEqual(run.result, EventLog.Result.FAILED)
        task.refresh_from_db()
        self.assertEqual(task.last_result, EventLog.Result.FAILED)
        run = TaskRun.objects.get(task=task)
        self.assertEqual(run.triggered_by, "auto")

    def test_database_rejects_invalid_task_command_and_schedule(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            self._make_task(command="missing_cmd")
        with self.assertRaises(IntegrityError), transaction.atomic():
            self._make_task(
                run_mode=TaskJob.RunMode.SCHEDULED,
                interval_minutes=None,
            )
        with self.assertRaises(IntegrityError), transaction.atomic():
            self._make_task(
                status=TaskJob.Status.RUNNING,
                last_started_at=None,
            )

    def test_database_rejects_invalid_task_run_lifecycle(self):
        task = self._make_task()
        started_at = timezone.now()

        with self.assertRaises(IntegrityError), transaction.atomic():
            TaskRun.objects.create(
                task=task,
                triggered_by="unknown",
                started_at=started_at,
            )
        with self.assertRaises(IntegrityError), transaction.atomic():
            TaskRun.objects.create(
                task=task,
                triggered_by=TaskRun.TriggeredBy.AUTO,
                started_at=started_at,
                result=TaskRun.Result.OK,
            )
        with self.assertRaises(IntegrityError), transaction.atomic():
            TaskRun.objects.create(
                task=task,
                triggered_by=TaskRun.TriggeredBy.AUTO,
                started_at=started_at,
                finished_at=started_at,
                result="",
            )

    def test_database_rejects_invalid_task_job_result_lifecycle(self):
        task = self._make_task()

        invalid_states = (
            {"last_result": "unknown"},
            {"last_result": TaskJob.Result.OK},
            {"last_finished_at": timezone.now()},
            {
                "status": TaskJob.Status.COMPLETED,
                "last_finished_at": timezone.now(),
                "last_result": TaskJob.Result.FAILED,
            },
            {
                "status": TaskJob.Status.FAILED,
                "last_finished_at": timezone.now(),
                "last_result": TaskJob.Result.OK,
            },
        )
        for invalid_state in invalid_states:
            with (
                self.subTest(invalid_state=invalid_state),
                self.assertRaises(IntegrityError),
                transaction.atomic(),
            ):
                TaskJob.objects.filter(pk=task.pk).update(**invalid_state)

    def test_toggle(self):
        self.client.force_login(self.admin)
        task = self._make_task()
        self.client.post(reverse("system:task_toggle", args=[task.pk]))
        task.refresh_from_db()
        self.assertFalse(task.enabled)
        self.assertTrue(
            EventLog.objects.filter(
                event_type=EventLog.EventType.UPDATE,
                user=self.admin,
                target=f"task:{task.pk}:disabled",
            ).exists()
        )

    def test_task_toggle_rolls_back_when_semantic_audit_fails(self):
        self.client.force_login(self.admin)
        task = self._make_task()

        with (
            patch("apps.system.views.log_event", side_effect=RuntimeError("audit")),
            self.assertRaises(RuntimeError),
        ):
            self.client.post(reverse("system:task_toggle", args=[task.pk]))

        task.refresh_from_db()
        self.assertTrue(task.enabled)

    def test_non_admin_cannot_run(self):
        self.client.force_login(self.operator)
        task = self._make_task()
        resp = self.client.post(reverse("system:task_run", args=[task.pk]))
        self.assertEqual(resp.status_code, 403)
        self.assertFalse(TaskRun.objects.exists())

    def test_task_file_download_requires_admin(self):
        task = self._make_task()
        attachment = TaskFile.objects.create(
            task=task,
            file=SimpleUploadedFile("result.txt", b"result"),
            uploaded_by=self.admin,
        )
        self.client.force_login(self.operator)
        denied = self.client.get(
            reverse("system:task_file_download", args=[attachment.pk])
        )
        self.assertEqual(denied.status_code, 403)
        self.assertFalse(
            EventLog.objects.filter(target=f"task-file:{attachment.pk}").exists()
        )
        self.client.force_login(self.admin)
        allowed = self.client.get(
            reverse("system:task_file_download", args=[attachment.pk])
        )
        self.assertEqual(allowed.status_code, 200)
        self.assertEqual(b"".join(allowed.streaming_content), b"result")
        self.assertTrue(
            EventLog.objects.filter(
                event_type=EventLog.EventType.EXPORT,
                user=self.admin,
                target=f"task-file:{attachment.pk}",
            ).exists()
        )

    def test_task_rejects_video_attachment_with_visible_error(self):
        task = self._make_task()
        self.client.force_login(self.admin)

        response = self.client.post(
            reverse("system:task_update", args=[task.pk]),
            {
                "action": "file",
                "file": SimpleUploadedFile(
                    "oversized-scope.mp4", b"video", content_type="video/mp4"
                ),
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(task.files.exists())
        self.assertContains(response, "допустимы документы и архивы до 20 МБ")

    def test_task_file_rollback_removes_storage_object(self):
        task = self._make_task()
        self.client.force_login(self.admin)

        with tempfile.TemporaryDirectory() as media_root, override_settings(
            MEDIA_ROOT=media_root
        ):
            with (
                patch(
                    "apps.system.views.log_event",
                    side_effect=RuntimeError("audit"),
                ),
                self.assertRaises(RuntimeError),
            ):
                self.client.post(
                    reverse("system:task_update", args=[task.pk]),
                    {
                        "action": "file",
                        "file": SimpleUploadedFile("rollback.txt", b"private"),
                    },
                )
            self.assertFalse(
                any(path.is_file() for path in Path(media_root).rglob("*"))
            )

        self.assertFalse(task.files.exists())

    @override_settings(MEDIA_ROOT=SYS_MEDIA_ROOT)
    def test_deleting_task_removes_cascaded_attachment_file(self):
        task = self._make_task()
        attachment = TaskFile.objects.create(
            task=task,
            file=SimpleUploadedFile("cascade-task.txt", b"task"),
            uploaded_by=self.admin,
        )
        storage = attachment.file.storage
        name = attachment.file.name
        self.assertTrue(storage.exists(name))

        with self.captureOnCommitCallbacks(execute=True):
            task.delete()

        self.assertFalse(storage.exists(name))

    def test_note_add_edit_delete(self):
        self.client.force_login(self.admin)
        task = self._make_task()
        url = reverse("system:task_update", args=[task.pk])
        resp = self.client.post(url, {"action": "note", "text": "Первая заметка"})
        self.assertEqual(resp.status_code, 302)
        note = task.notes.get()
        self.assertEqual(note.text, "Первая заметка")
        resp = self.client.post(
            url, {"action": "note_edit", "note_id": note.pk, "text": "Изменённая заметка"}
        )
        self.assertEqual(resp.status_code, 302)
        note.refresh_from_db()
        self.assertEqual(note.text, "Изменённая заметка")
        note_id = note.pk
        resp = self.client.post(url, {"action": "note_delete", "note_id": note_id})
        self.assertEqual(resp.status_code, 302)
        self.assertFalse(task.notes.exists())
        self.assertTrue(
            EventLog.objects.filter(
                event_type=EventLog.EventType.DELETE,
                user=self.admin,
                target=f"task:{task.pk}:note:{note_id}",
            ).exists()
        )

    def test_assignee_suggest(self):
        self.client.force_login(self.admin)
        resp = self.client.get(reverse("system:task_assignee_suggest"), {"q": "petr"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["suggestions"], [])
        employee = self.admin
        employee.first_name = "Иван"
        employee.last_name = "Петров"
        employee.save()
        resp = self.client.get(reverse("system:task_assignee_suggest"), {"q": "Иван"})
        self.assertEqual(resp.status_code, 200)
        labels = [s["label"] for s in resp.json()["suggestions"]]
        self.assertTrue(any("Петров" in lbl for lbl in labels))
        short = self.client.get(reverse("system:task_assignee_suggest"), {"q": "Ив"})
        self.assertEqual(short.json()["suggestions"], [])

    def test_assignee_suggest_excludes_inactive_and_limits_in_database(self):
        Employee.objects.create_user(
            username="inactive_task_user",
            first_name="СЕРГЕЙ",
            last_name="Скрытый",
            org=81000,
            is_active=False,
        )
        self.client.force_login(self.admin)

        with CaptureQueriesContext(connection) as captured:
            response = self.client.get(
                reverse("system:task_assignee_suggest"), {"q": "сергей"}
            )

        self.assertEqual(response.json()["suggestions"], [])
        employee_queries = [
            query["sql"].lower()
            for query in captured.captured_queries
            if "employee_employee" in query["sql"].lower()
        ]
        self.assertTrue(any("translate" in sql and "limit 10" in sql for sql in employee_queries))

    def test_due_and_run_tasks_command(self):
        from io import StringIO

        from django.core.management import call_command
        from django.utils import timezone

        task = self._make_task(
            command="noop",
            run_mode=TaskJob.RunMode.SCHEDULED,
            interval_minutes=10,
            last_started_at=timezone.now() - datetime.timedelta(minutes=30),
            last_finished_at=timezone.now() - datetime.timedelta(minutes=30),
            last_result=TaskJob.Result.OK,
            enabled=True,
        )
        out = StringIO()
        call_command("run_tasks", stdout=out)
        task.refresh_from_db()
        self.assertEqual(task.last_result, EventLog.Result.OK)
        self.assertIn("task", out.getvalue())

    @patch("apps.system.management.commands.run_scheduler.call_command")
    def test_scheduler_once_runs_exactly_one_task_cycle(self, run_tasks):
        call_command("run_scheduler", once=True, interval=5, stdout=io.StringIO())

        run_tasks.assert_called_once()
        self.assertEqual(run_tasks.call_args.args, ("run_tasks",))

    def test_scheduler_rejects_non_positive_interval(self):
        with self.assertRaisesMessage(CommandError, "не меньше 1 секунды"):
            call_command("run_scheduler", once=True, interval=0, stdout=io.StringIO())

    def test_recover_stale_run_closes_run_and_audit_event(self):
        from io import StringIO

        from django.core.management import call_command
        from django.utils import timezone

        started_at = timezone.now() - datetime.timedelta(hours=2)
        task = self._make_task(
            status=TaskJob.Status.RUNNING,
            last_started_at=started_at,
        )
        run = TaskRun.objects.create(
            task=task,
            triggered_by="auto",
            started_at=started_at,
        )
        event = log_event(
            module="system",
            event_type=EventLog.EventType.TASK,
            target=f"task:{task.pk}:{task.command}",
            pending=True,
        )
        out = StringIO()
        call_command("run_tasks", "--recover-only", "--stale-after=3600", stdout=out)

        task.refresh_from_db()
        run.refresh_from_db()
        event.refresh_from_db()
        self.assertEqual(task.status, TaskJob.Status.FAILED)
        self.assertEqual(task.last_result, EventLog.Result.FAILED)
        self.assertEqual(run.result, EventLog.Result.FAILED)
        self.assertIsNotNone(run.finished_at)
        self.assertEqual(event.result, EventLog.Result.FAILED)
        self.assertIsNotNone(event.finished_at)
        self.assertIn("Зависших запусков закрыто: 1", out.getvalue())

    def test_recover_stale_leaves_fresh_run_untouched(self):
        from django.utils import timezone

        task = self._make_task(
            status=TaskJob.Status.RUNNING,
            last_started_at=timezone.now(),
        )
        self.assertEqual(TaskJob.recover_stale(stale_after_seconds=3600), 0)
        task.refresh_from_db()
        self.assertEqual(task.status, TaskJob.Status.RUNNING)

    def test_not_due_not_run(self):
        from io import StringIO

        from django.core.management import call_command
        from django.utils import timezone

        self._make_task(
            command="noop",
            run_mode=TaskJob.RunMode.SCHEDULED,
            interval_minutes=70,
            last_started_at=timezone.now(),
            last_finished_at=timezone.now(),
            last_result=TaskJob.Result.OK,
            enabled=True,
        )
        out = StringIO()
        call_command("run_tasks", stdout=out)
        self.assertEqual(TaskRun.objects.count(), 0)
        self.assertIn("Нет заданий", out.getvalue())


class NewsSlugConcurrencyTests(TransactionTestCase):
    def test_concurrent_equal_titles_receive_distinct_bounded_slugs(self):
        barrier = Barrier(2)
        thread_state = threading.local()
        original_exists = QuerySet.exists

        def synchronize_first_news_slug_check(queryset):
            exists = original_exists(queryset)
            if queryset.model is NewsItem and not getattr(thread_state, "checked", False):
                thread_state.checked = True
                barrier.wait(timeout=5)
            return exists

        def create_news():
            connection.close()
            try:
                item = NewsItem.objects.create(title="Long title " * 18, text="Текст")
                return item.slug
            finally:
                connection.close()

        with (
            patch.object(QuerySet, "exists", synchronize_first_news_slug_check),
            ThreadPoolExecutor(max_workers=2) as executor,
        ):
            slugs = list(executor.map(lambda _: create_news(), range(2)))

        self.assertEqual(len(set(slugs)), 2)
        self.assertTrue(all(len(slug) <= 50 for slug in slugs))
        self.assertEqual(NewsItem.objects.count(), 2)


class TaskEnabledStateMigrationTests(TransactionTestCase):
    migrate_from = [("system", "0010_require_message_attachment_reply")]
    migrate_to = [("system", "0011_enforce_task_enabled_state")]

    def test_migration_normalizes_existing_enabled_cancelled_task(self):
        executor = MigrationExecutor(connection)
        executor.migrate(self.migrate_from)
        old_apps = executor.loader.project_state(self.migrate_from).apps
        OldTaskJob = old_apps.get_model("system", "TaskJob")
        task = OldTaskJob.objects.create(
            name="Legacy active cancelled",
            command="noop",
            status="cancelled",
            enabled=True,
            run_mode="manual",
        )

        executor = MigrationExecutor(connection)
        executor.migrate(self.migrate_to)
        new_apps = executor.loader.project_state(self.migrate_to).apps
        NewTaskJob = new_apps.get_model("system", "TaskJob")

        self.assertEqual(NewTaskJob.objects.get(pk=task.pk).status, "created")


class TaskRunLifecycleMigrationTests(TransactionTestCase):
    migrate_from = [("system", "0011_enforce_task_enabled_state")]
    migrate_to = [("system", "0012_enforce_taskrun_lifecycle")]

    def test_migration_normalizes_legacy_task_run_states(self):
        executor = MigrationExecutor(connection)
        executor.migrate(self.migrate_from)
        old_apps = executor.loader.project_state(self.migrate_from).apps
        OldTaskJob = old_apps.get_model("system", "TaskJob")
        OldTaskRun = old_apps.get_model("system", "TaskRun")
        task = OldTaskJob.objects.create(
            name="Legacy runs",
            command="noop",
            status="created",
            enabled=False,
            run_mode="manual",
        )
        started_at = timezone.now()
        pending = OldTaskRun.objects.create(
            task=task,
            triggered_by="unknown",
            started_at=started_at,
            result="ok",
        )
        finished = OldTaskRun.objects.create(
            task=task,
            triggered_by="auto",
            started_at=started_at,
            finished_at=started_at,
            result="",
        )

        executor = MigrationExecutor(connection)
        executor.migrate(self.migrate_to)
        new_apps = executor.loader.project_state(self.migrate_to).apps
        NewTaskRun = new_apps.get_model("system", "TaskRun")

        pending = NewTaskRun.objects.get(pk=pending.pk)
        finished = NewTaskRun.objects.get(pk=finished.pk)
        self.assertEqual(pending.triggered_by, "legacy")
        self.assertEqual(pending.result, "")
        self.assertEqual(finished.triggered_by, "auto")
        self.assertEqual(finished.result, "failed")


class TaskLastResultMigrationTests(TransactionTestCase):
    migrate_from = [("system", "0012_enforce_taskrun_lifecycle")]
    migrate_to = [("system", "0013_enforce_task_last_result_state")]

    def test_migration_normalizes_inconsistent_task_aggregates(self):
        executor = MigrationExecutor(connection)
        executor.migrate(self.migrate_from)
        old_apps = executor.loader.project_state(self.migrate_from).apps
        OldTaskJob = old_apps.get_model("system", "TaskJob")
        started_at = timezone.now() - datetime.timedelta(minutes=5)
        missing_finish = OldTaskJob.objects.create(
            name="Legacy terminal without finish",
            command="noop",
            status="completed",
            enabled=True,
            run_mode="manual",
            last_started_at=started_at,
            last_result="unknown",
        )
        pending_with_result = OldTaskJob.objects.create(
            name="Legacy pending with result",
            command="noop",
            status="created",
            enabled=True,
            run_mode="manual",
            last_result="ok",
        )
        completed_as_failed = OldTaskJob.objects.create(
            name="Legacy completed mismatch",
            command="noop",
            status="completed",
            enabled=True,
            run_mode="manual",
            last_started_at=started_at,
            last_finished_at=timezone.now(),
            last_result="failed",
        )

        executor = MigrationExecutor(connection)
        executor.migrate(self.migrate_to)
        new_apps = executor.loader.project_state(self.migrate_to).apps
        NewTaskJob = new_apps.get_model("system", "TaskJob")

        missing_finish = NewTaskJob.objects.get(pk=missing_finish.pk)
        pending_with_result = NewTaskJob.objects.get(pk=pending_with_result.pk)
        completed_as_failed = NewTaskJob.objects.get(pk=completed_as_failed.pk)
        self.assertEqual(missing_finish.status, "failed")
        self.assertEqual(missing_finish.last_finished_at, started_at)
        self.assertEqual(missing_finish.last_result, "failed")
        self.assertEqual(pending_with_result.last_result, "")
        self.assertIsNone(pending_with_result.last_finished_at)
        self.assertEqual(completed_as_failed.status, "failed")
        self.assertEqual(completed_as_failed.last_result, "failed")


class PrefTests(BaseSystemTestCase):
    def setUp(self):
        super().setUp()
        self.theme = IrpTheme.objects.create(
            code_name="PP.PP", title="Настройка", version=3
        )

    def _make_irp(self, owner=None):
        owner = owner or self.operator
        return Irp.objects.create(
            n_irp=f"00000000-0000-0000-0000-{str(owner.pk).zfill(12)}",
            irp_type=1,
            date_create=datetime.date.today(),
            way=1,
            how=1,
            theme=self.theme,
            otv_t=1,
            otv_kon=owner.org,
            employee_one=owner,
            data_plan=datetime.date.today() + datetime.timedelta(days=30),
            z_f="Петров",
            text="x",
        )

    def test_ui_preferences_expose_required_accessibility_modes(self):
        self.client.force_login(self.operator)
        response = self.client.get(reverse("system:prefs"))

        self.assertContains(response, 'data-ui-font="base"')
        self.assertContains(response, 'data-ui-font="a"')
        self.assertContains(response, 'data-ui-font="a-plus"')
        self.assertContains(response, 'data-ui-font="a-plus-plus"')
        self.assertContains(response, 'data-ui-contrast="white"')
        self.assertContains(response, 'data-ui-contrast="black"')
        self.assertContains(response, 'aria-labelledby="font-scale-label"')
        self.assertContains(response, 'aria-labelledby="contrast-label"')

    def test_save_table_prefs(self):
        self.client.force_login(self.operator)
        resp = self.client.post(
            reverse("system:table_prefs", args=[JOURNAL_TABLE_KEY]),
            {
                "columns": ["z_f", "id"],
                "order_id": "1",
                "order_z_f": "0",
                "sort_field": "date_create",
                "sort_dir": "-",
                "fixed_first": "on",
            },
        )
        self.assertEqual(resp.status_code, 302)
        pref = UserTableViewPref.objects.get(user=self.operator, table_key=JOURNAL_TABLE_KEY)
        self.assertEqual(pref.columns, ["z_f", "id"])
        self.assertEqual(pref.sorting, {"field": "date_create", "dir": "-"})
        self.assertTrue(pref.fixed_first)

    def test_table_prefs_save_rolls_back_when_audit_fails(self):
        original = UserTableViewPref.objects.create(
            user=self.operator,
            table_key=JOURNAL_TABLE_KEY,
            columns=["id", "status"],
            sorting={"field": "id", "dir": ""},
        )
        self.client.force_login(self.operator)

        with (
            patch("apps.system.views.log_event", side_effect=RuntimeError("audit")),
            self.assertRaises(RuntimeError),
        ):
            self.client.post(
                reverse("system:table_prefs", args=[JOURNAL_TABLE_KEY]),
                {"columns": ["z_f"], "sort_field": "z_f", "sort_dir": "-"},
            )

        original.refresh_from_db()
        self.assertEqual(original.columns, ["id", "status"])
        self.assertEqual(original.sorting, {"field": "id", "dir": ""})

    def test_journal_uses_columns_pref(self):
        self._make_irp()
        UserTableViewPref.objects.create(
            user=self.operator,
            table_key=JOURNAL_TABLE_KEY,
            columns=["id", "z_f", "status"],
            fixed_first=True,
        )
        self.client.force_login(self.operator)
        resp = self.client.get(reverse("journal:list"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, ">Заявитель</a>")
        self.assertContains(resp, "Статус")
        self.assertContains(resp, "th-sticky")
        self.assertNotContains(resp, "УНр")
        self.assertNotContains(resp, "Принял")
        self.assertNotContains(resp, ">Дата</a>")

        self.assertEqual([column["key"] for column in resp.context["cols"]], ["id", "z_f", "status"])

    def test_journal_applies_saved_column_order(self):
        self._make_irp()
        UserTableViewPref.objects.create(
            user=self.operator,
            table_key=JOURNAL_TABLE_KEY,
            columns=["status", "z_f", "id"],
        )
        self.client.force_login(self.operator)
        response = self.client.get(reverse("journal:list"))
        self.assertEqual(
            [column["key"] for column in response.context["cols"]],
            ["status", "z_f", "id"],
        )

    def test_preferences_form_preserves_saved_column_order(self):
        UserTableViewPref.objects.create(
            user=self.operator,
            table_key=JOURNAL_TABLE_KEY,
            columns=["status", "id"],
        )
        self.client.force_login(self.operator)
        response = self.client.get(
            reverse("system:table_prefs", args=[JOURNAL_TABLE_KEY])
        )
        content = response.content.decode()
        self.assertLess(content.index('value="status"'), content.index('value="id"'))

    def test_journal_uses_pref_sort(self):
        self._make_irp()
        UserTableViewPref.objects.create(
            user=self.operator,
            table_key=JOURNAL_TABLE_KEY,
            columns=[],
            sorting={"field": "id", "dir": ""},
        )
        self.client.force_login(self.operator)
        resp = self.client.get(reverse("journal:list"))
        self.assertContains(resp, "?sort=-id")

    def test_pref_columns_default_all(self):
        self._make_irp()
        self.client.force_login(self.operator)
        resp = self.client.get(reverse("journal:list"))
        self.assertContains(resp, "УНр")
        self.assertContains(resp, ">Поступило</a>")
        self.assertContains(resp, ">Срок рассм.</a>")
        self.assertContains(resp, ">Закрыто</a>")
        self.assertFalse(
            UserTableViewPref.objects.filter(user=self.operator).exists()
        )


class RequestScreensTests(BaseSystemTestCase):
    def test_messages_page_shows_menu_open(self):
        self.client.force_login(self.operator)
        resp = self.client.get(reverse("system:messages"))
        self.assertContains(resp, "Сообщения")


class _FakeUpload:
    """Файловый объект без выделения памяти (attr name/size)."""

    def __init__(self, name, size):
        self.name = name
        self.size = size


class DocUploadSecurityTests(BaseSystemTestCase):
    """Безопасность загрузок документов (Этап 7, 2 класс ФСТЭК)."""

    @override_settings(MEDIA_ROOT=SYS_MEDIA_ROOT)
    def test_validator_rejects_unsafe_extension(self):
        with self.assertRaises(ValidationError):
            validate_document_file(_FakeUpload("script.exe", 1024))
        with self.assertRaises(ValidationError):
            validate_document_file(_FakeUpload("pivot.xls.php", 1024))

    @override_settings(MEDIA_ROOT=SYS_MEDIA_ROOT)
    def test_validator_accepts_allowed_extension(self):
        validate_document_file(_FakeUpload("manual.pdf", 1024))
        validate_document_file(_FakeUpload("training.mp4", DOC_MAX_SIZE_BYTES + 1))

    @override_settings(MEDIA_ROOT=SYS_MEDIA_ROOT)
    def test_validator_rejects_oversize(self):
        with self.assertRaises(ValidationError):
            validate_document_file(_FakeUpload("big.pdf", DOC_MAX_SIZE_BYTES + 1))
        with self.assertRaises(ValidationError):
            validate_document_file(_FakeUpload("big.webm", VIDEO_MAX_SIZE_BYTES + 1))

    def test_working_attachments_exclude_video_and_keep_20_mb_limit(self):
        validate_attachment_file(_FakeUpload("evidence.pdf", DOC_MAX_SIZE_BYTES))
        with self.assertRaises(ValidationError):
            validate_attachment_file(_FakeUpload("training.mp4", 1024))
        with self.assertRaises(ValidationError):
            validate_attachment_file(
                _FakeUpload("oversized.pdf", DOC_MAX_SIZE_BYTES + 1)
            )

    def test_task_attachment_picker_matches_server_allowlist(self):
        from apps.system.forms import TaskFileForm

        accept = TaskFileForm().fields["file"].widget.attrs["accept"]

        self.assertEqual(accept, ",".join(sorted(ALLOWED_ATTACHMENT_EXTENSIONS)))
        self.assertNotIn(".mp4", accept)
        self.assertNotIn(".csv", accept)

    @override_settings(MEDIA_ROOT=SYS_MEDIA_ROOT)
    def test_upload_video_is_available_in_documentation(self):
        self.client.force_login(self.admin)
        response = self.client.post(
            reverse("system:doc_upload"),
            {
                "title": "Обучающий видеоролик",
                "sort_order": "1",
                "file": SimpleUploadedFile(
                    "training.mp4", b"video-placeholder", content_type="video/mp4"
                ),
            },
            follow=True,
        )
        self.assertContains(response, "Обучающий видеоролик")
        document = SystemDocument.objects.get(title="Обучающий видеоролик")
        self.assertEqual(document.file_type, "mp4")

    @override_settings(MEDIA_ROOT=SYS_MEDIA_ROOT)
    def test_upload_unsafe_extension_rejected_by_view(self):
        self.client.force_login(self.admin)
        resp = self.client.post(
            reverse("system:doc_upload"),
            {"title": "Угроза", "file": SimpleUploadedFile("evil.php", b"<?php")},
            follow=True,
        )
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(SystemDocument.objects.filter(title="Угроза").exists())
        self.assertIn(
            "Недопустимый тип файла",
            " ".join(str(m) for m in messages.get_messages(resp.wsgi_request)),
        )

    @override_settings(MEDIA_ROOT=SYS_MEDIA_ROOT)
    def test_csrf_required_for_upload(self):
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.admin)
        resp = csrf_client.post(
            reverse("system:doc_upload"),
            {"title": "x", "file": SimpleUploadedFile("x.pdf", b"x")},
        )
        self.assertEqual(resp.status_code, 403)

    def test_streaming_upload_limit_returns_413_before_view(self):
        self.client.force_login(self.admin)

        with patch("apps.core.uploads.MAX_UPLOAD_SIZE_BYTES", 4):
            response = self.client.post(
                reverse("system:doc_upload"),
                {
                    "title": "Слишком большой",
                    "file": SimpleUploadedFile("oversized.pdf", b"12345"),
                },
            )

        self.assertEqual(response.status_code, 413)
        self.assertFalse(SystemDocument.objects.filter(title="Слишком большой").exists())
        event = EventLog.objects.get(target="POST /system/docs/upload/")
        self.assertEqual(event.result, EventLog.Result.FAILED)


class SecurityHeaderTests(BaseSystemTestCase):
    def test_security_headers_present(self):
        self.client.force_login(self.operator)
        resp = self.client.get(reverse("system:messages"))
        self.assertEqual(resp.headers["X-Frame-Options"], "DENY")
        self.assertEqual(resp.headers["X-Content-Type-Options"], "nosniff")
        self.assertEqual(resp.headers.get("Referrer-Policy"), "same-origin")
        self.assertEqual(
            resp.headers["Permissions-Policy"],
            "camera=(), geolocation=(), microphone=(), payment=(), usb=()",
        )
        self.assertEqual(resp.headers["Cross-Origin-Opener-Policy"], "same-origin")
        policy = resp.headers.get("Content-Security-Policy", "")
        self.assertIn("script-src 'self'", policy)
        self.assertIn("style-src 'self'", policy)
        self.assertNotIn("'unsafe-inline'", policy)
        self.assertEqual(
            resp.headers["Cache-Control"],
            "no-store, no-cache, max-age=0, private",
        )
        self.assertEqual(resp.headers["Pragma"], "no-cache")
        self.assertEqual(resp.headers["Expires"], "0")

    def test_anonymous_redirected_to_login(self):
        resp = self.client.get(reverse("system:users"))
        self.assertRedirects(resp, "/accounts/login/?next=/system/users/")
        self.assertIn("no-store", resp.headers["Cache-Control"])
        self.assertIn("camera=()", resp.headers["Permissions-Policy"])

    def test_error_response_is_not_cacheable(self):
        resp = self.client.get("/missing-sensitive-page/")

        self.assertEqual(resp.status_code, 404)
        self.assertIn("no-store", resp.headers["Cache-Control"])
        self.assertEqual(resp.headers["Pragma"], "no-cache")
        self.assertIn("camera=()", resp.headers["Permissions-Policy"])

    def test_non_admin_forbidden_on_admin_screens(self):
        self.client.force_login(self.operator)
        resp = self.client.get(reverse("system:users"))
        self.assertEqual(resp.status_code, 403)
        event = EventLog.objects.get(target="GET /system/users/")
        self.assertEqual(event.result, EventLog.Result.DENIED)

    def test_not_found_is_recorded_as_failure_not_access_denial(self):
        resp = self.client.get("/missing-sensitive-page/")

        self.assertEqual(resp.status_code, 404)
        event = EventLog.objects.get(target="GET /missing-sensitive-page/")
        self.assertEqual(event.result, EventLog.Result.FAILED)

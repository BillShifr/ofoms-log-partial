"""Тесты общесистемных модулей (ТЗ разд. 3.2–3.8)."""

import datetime
import tempfile

from django.contrib import messages
from django.contrib.auth.models import Group
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection
from django.test import Client, TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from apps.core.models import EventLog, log_event
from apps.core.roles import ensure_role_groups
from apps.employee.models import Employee
from apps.journal.models import Irp, IrpTheme
from apps.journal.table import JOURNAL_TABLE_KEY
from apps.system.models import (
    Conversation,
    MessageAttachment,
    MessageReply,
    MessageThread,
    NewsCategory,
    NewsItem,
    SystemDocument,
    TaskAlreadyRunning,
    TaskFile,
    TaskJob,
    TaskRun,
    UserTableViewPref,
)
from apps.system.validators import (
    DOC_MAX_SIZE_BYTES,
    IMAGE_MAX_SIZE_BYTES,
    VIDEO_MAX_SIZE_BYTES,
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
        resp = self.client.post(
            reverse("system:react", args=[reply.pk]), {"emoji": "👍"}
        )
        self.assertEqual(resp.status_code, 302)
        reply.refresh_from_db()
        self.assertNotIn("👍", reply.reactions)

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
        self.client.force_login(self.operator)
        allowed = self.client.get(
            reverse("system:message_attachment_download", args=[attachment.pk])
        )
        self.assertEqual(allowed.status_code, 200)
        self.assertEqual(b"".join(allowed.streaming_content), b"private")

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
        task = self._make_task(status=TaskJob.Status.RUNNING)
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

    def test_failed_command_logged(self):
        task = self._make_task(command="missing_cmd")
        run = task.run()
        self.assertEqual(run.result, EventLog.Result.FAILED)
        task.refresh_from_db()
        self.assertEqual(task.last_result, EventLog.Result.FAILED)
        run = TaskRun.objects.get(task=task)
        self.assertEqual(run.triggered_by, "auto")

    def test_toggle(self):
        self.client.force_login(self.admin)
        task = self._make_task()
        self.client.post(reverse("system:task_toggle", args=[task.pk]))
        task.refresh_from_db()
        self.assertFalse(task.enabled)

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
        self.client.force_login(self.admin)
        allowed = self.client.get(
            reverse("system:task_file_download", args=[attachment.pk])
        )
        self.assertEqual(allowed.status_code, 200)
        self.assertEqual(b"".join(allowed.streaming_content), b"result")

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
        resp = self.client.post(url, {"action": "note_delete", "note_id": note.pk})
        self.assertEqual(resp.status_code, 302)
        self.assertFalse(task.notes.exists())

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
            enabled=True,
        )
        out = StringIO()
        call_command("run_tasks", stdout=out)
        task.refresh_from_db()
        self.assertEqual(task.last_result, EventLog.Result.OK)
        self.assertIn("task", out.getvalue())

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
            enabled=True,
        )
        out = StringIO()
        call_command("run_tasks", stdout=out)
        self.assertEqual(TaskRun.objects.count(), 0)
        self.assertIn("Нет заданий", out.getvalue())


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


class SecurityHeaderTests(BaseSystemTestCase):
    def test_security_headers_present(self):
        self.client.force_login(self.operator)
        resp = self.client.get(reverse("system:messages"))
        self.assertEqual(resp.headers["X-Frame-Options"], "DENY")
        self.assertEqual(resp.headers["X-Content-Type-Options"], "nosniff")
        self.assertEqual(resp.headers.get("Referrer-Policy"), "same-origin")
        policy = resp.headers.get("Content-Security-Policy", "")
        self.assertIn("script-src 'self'", policy)
        self.assertNotIn("'unsafe-inline'", policy.split("style-src", 1)[0])

    def test_anonymous_redirected_to_login(self):
        resp = self.client.get(reverse("system:users"))
        self.assertRedirects(resp, "/accounts/login/?next=/system/users/")

    def test_non_admin_forbidden_on_admin_screens(self):
        self.client.force_login(self.operator)
        resp = self.client.get(reverse("system:users"))
        self.assertEqual(resp.status_code, 403)

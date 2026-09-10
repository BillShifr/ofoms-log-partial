"""Тесты journal: модели Irp и IrpTheme,(XmlFiles), а также экраны журнала.

Покрытие Этапа 2: RBAC-ограничение СМО, реестр, создание, редактирование,
история изменений.
"""

import datetime
import tempfile

from django.test import TestCase, override_settings
from django.urls import reverse

from apps.employee.models import Employee
from apps.journal.models import Irp, IrpFile, IrpHistory, IrpTheme

ROUTING_MEDIA_ROOT = tempfile.mkdtemp(prefix="ejournal_test_media_")


class IrpThemeTests(TestCase):
    def setUp(self):
        self.theme = IrpTheme.objects.create(
            code_name="XX.XX", title="Тестовая тема", version=1
        )

    def test_str(self):
        self.assertEqual(str(self.theme), "XX.XX - Тестовая тема")

    def test_unique_together(self):
        IrpTheme.objects.create(code_name="XX.XX", title="v2", version=2)
        self.assertEqual(IrpTheme.objects.count(), 2)


class IrpModelTests(TestCase):
    def setUp(self):
        self.theme = IrpTheme.objects.create(
            code_name="YY.YY", title="Миграция", version=3
        )
        self.employee = Employee.objects.create_user(
            username="emp_irp", password="GoodPass!1", org=81000
        )

    def _create_irp(self, date_close=None, data_plan=None):
        return Irp.objects.create(
            n_irp="00000000-0000-0000-0000-000000000001",
            irp_type=1,
            date_create=datetime.date.today(),
            way=1,
            how=1,
            theme=self.theme,
            otv_t=1,
            otv_kon=81000,
            employee_one=self.employee,
            data_plan=data_plan or datetime.date.today() + datetime.timedelta(days=30),
            z_f="Заявитель",
            date_close=date_close,
        )

    def test_is_closed(self):
        irp = self._create_irp(date_close=datetime.date.today())
        self.assertTrue(irp.is_closed)

    def test_is_overdue(self):
        yesterday = datetime.date.today() - datetime.timedelta(days=1)
        irp = self._create_irp(data_plan=yesterday)
        self.assertTrue(irp.is_overdue)

    def test_not_overdue_when_closed(self):
        yesterday = datetime.date.today() - datetime.timedelta(days=1)
        irp = self._create_irp(data_plan=yesterday, date_close=datetime.date.today())
        self.assertFalse(irp.is_overdue)


class JournalScreenTests(TestCase):
    """Тесты экранов журнала (Этап 2)."""

    def setUp(self):
        self.theme = IrpTheme.objects.create(
            code_name="ZZ.ZZ", title="Доступ", version=3
        )
        self.tfoms_user = Employee.objects.create_user(
            username="tfoms_op", password="GoodPass!1", org=81000
        )
        self.smo_user = Employee.objects.create_user(
            username="smo_agent", password="GoodPass!1", org=81001
        )

    def _make_irp(self, owner=None):
        owner = owner or self.tfoms_user
        return Irp.objects.create(
            n_irp=self._plain_uuid(),
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
        )

    @staticmethod
    def _plain_uuid():
        import uuid

        return str(uuid.uuid4())

    def test_list_requires_login(self):
        resp = self.client.get(reverse("journal:list"))
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/accounts/login", resp.url)

    def test_list_shows_irp(self):
        self._make_irp()
        self.client.force_login(self.tfoms_user)
        resp = self.client.get(reverse("journal:list"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Петров")

    def test_filter_finds_cyrillic_case_insensitive(self):
        # Локаль PG = C: __icontains не сворачивает кириллицу — ищем через fold
        self._make_irp()
        self.client.force_login(self.tfoms_user)
        resp = self.client.get(reverse("journal:list"), {"z_f": "петров"})
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Петров")

    def test_filter_folds_z_enp_and_n_irp(self):
        irp = self._make_irp()
        irp.n_irp = "ABC-12345"
        irp.z_enp = "ИВАНОВ-ИВАН"
        irp.save()
        self.client.force_login(self.tfoms_user)
        for params in ({"n_irp": "abc-123"}, {"z_enp": "иванов-ива"}, {"z_f": "петров"}):
            resp = self.client.get(reverse("journal:list"), params)
            self.assertEqual(resp.status_code, 200)
            self.assertContains(resp, "Петров")

    def test_smo_sees_only_own(self):
        own = self._make_irp(owner=self.smo_user)
        other = self._make_irp(owner=self.tfoms_user)
        self.client.force_login(self.smo_user)
        resp = self.client.get(reverse("journal:list"))
        self.assertContains(resp, own.n_irp)
        self.assertNotContains(resp, other.n_irp)

    def test_smo_cannot_open_foreign_detail(self):
        other = self._make_irp(owner=self.tfoms_user)
        self.client.force_login(self.smo_user)
        resp = self.client.get(reverse("journal:detail", args=[other.pk]))
        self.assertEqual(resp.status_code, 403)

    def test_detail_shows_requisites(self):
        irp = self._make_irp()
        self.client.force_login(self.tfoms_user)
        resp = self.client.get(reverse("journal:detail", args=[irp.pk]))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Петров")
        self.assertContains(resp, irp.get_irp_type_display())

    def test_create_records_history(self):
        self.client.force_login(self.tfoms_user)
        resp = self.client.post(
            reverse("journal:create"),
            {
                "irp_type": 2,
                "date_create": datetime.date.today().isoformat(),
                "way": 1,
                "how": 2,
                "theme": self.theme.pk,
                "otv_t": 1,
                "otv_kon": 81000,
                "employee_one": self.tfoms_user.pk,
                "line_one": 1,
                "data_plan": (
                    datetime.date.today() + datetime.timedelta(days=30)
                ).isoformat(),
                "z_f": "Сидоров",
            },
        )
        self.assertEqual(resp.status_code, 302)
        irp = Irp.objects.get(z_f="Сидоров")
        self.assertTrue(IrpHistory.objects.filter(irp=irp).exists())
        # заявитель зафиксирован как инициатор создания
        self.assertEqual(irp.employee_one, self.tfoms_user)

    def test_edit_writes_history_diff(self):
        irp = self._make_irp()
        self.client.force_login(self.tfoms_user)
        resp = self.client.post(
            reverse("journal:edit", args=[irp.pk]),
            {
                "n_irp": irp.n_irp,
                "irp_type": 1,
                "date_create": irp.date_create.isoformat(),
                "way": 2,
                "how": 1,
                "theme": self.theme.pk,
                "otv_t": 1,
                "otv_kon": 81000,
                "employee_one": self.tfoms_user.pk,
                "line_one": 1,
                "data_plan": irp.data_plan.isoformat(),
                "z_f": "Иванов",  # изменено
                "date_close": datetime.date.today().isoformat(),
            },
        )
        self.assertEqual(resp.status_code, 302)
        irp.refresh_from_db()
        self.assertEqual(irp.z_f, "Иванов")
        entry = IrpHistory.objects.filter(irp=irp, field_name="z_f").latest("id")
        self.assertEqual(entry.old_value, "Петров")
        self.assertEqual(entry.new_value, "Иванов")

    def test_print_requires_login(self):
        irp = self._make_irp()
        resp = self.client.get(reverse("journal:print", args=[irp.pk]))
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/accounts/login", resp.url)

    def test_print_smo_foreign_forbidden(self):
        other = self._make_irp(owner=self.tfoms_user)
        self.client.force_login(self.smo_user)
        resp = self.client.get(reverse("journal:print", args=[other.pk]))
        self.assertEqual(resp.status_code, 403)

    def test_print_renders_card(self):
        irp = self._make_irp()
        self.client.force_login(self.tfoms_user)
        resp = self.client.get(reverse("journal:print", args=[irp.pk]))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Петров")
        self.assertContains(resp, "Печать")


@override_settings(MEDIA_ROOT=ROUTING_MEDIA_ROOT)
class RoutingTests(TestCase):
    """Этап 4: ответы (п. 215), файлы (п. 200), переадресация (п. 212)."""

    def setUp(self):
        self.theme = IrpTheme.objects.create(
            code_name="RR.RR", title="Маршрутизация", version=3
        )
        self.tfoms_user = Employee.objects.create_user(
            username="routing_op", password="GoodPass!1", org=81000
        )
        self.smo_user = Employee.objects.create_user(
            username="routing_smo", password="GoodPass!1", org=81001
        )

    def _make_irp(self, owner=None):
        owner = owner or self.tfoms_user
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
            text="Прошу разобраться",
        )

    def test_answer_requires_login(self):
        irp = self._make_irp()
        resp = self.client.post(reverse("journal:answer", args=[irp.pk]), {"text": "x"})
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/accounts/login", resp.url)

    def test_answer_smo_foreign_forbidden(self):
        other = self._make_irp(owner=self.tfoms_user)
        self.client.force_login(self.smo_user)
        resp = self.client.post(reverse("journal:answer", args=[other.pk]), {"text": "x"})
        self.assertEqual(resp.status_code, 403)

    def test_answer_creates_answer_and_history(self):
        irp = self._make_irp()
        self.client.force_login(self.tfoms_user)
        resp = self.client.post(
            reverse("journal:answer", args=[irp.pk]),
            {"text": "Предварительный ответ подготовлен", "is_preliminary": "on"},
        )
        self.assertEqual(resp.status_code, 302)
        answer = irp.answers.get()
        self.assertTrue(answer.is_preliminary)
        self.assertEqual(answer.user, self.tfoms_user)
        self.assertTrue(IrpHistory.objects.filter(irp=irp, field_name="answer").exists())

    def test_final_answer_flag(self):
        irp = self._make_irp()
        self.client.force_login(self.tfoms_user)
        self.client.post(
            reverse("journal:answer", args=[irp.pk]),
            {"text": "Итоговый ответ", "is_preliminary": ""},
        )
        self.assertFalse(irp.answers.get().is_preliminary)

    def test_answer_form_rejects_empty_text(self):
        irp = self._make_irp()
        self.client.force_login(self.tfoms_user)
        resp = self.client.post(reverse("journal:answer", args=[irp.pk]), {"text": "  "})
        self.assertEqual(resp.status_code, 302)
        self.assertFalse(irp.answers.exists())

    def test_file_upload_attaches_to_irp(self):
        from django.core.files.uploadedfile import SimpleUploadedFile

        irp = self._make_irp()
        self.client.force_login(self.tfoms_user)
        resp = self.client.post(
            reverse("journal:file", args=[irp.pk]),
            {"file": SimpleUploadedFile("doc.txt", b"content")},
        )
        self.assertEqual(resp.status_code, 302)
        f = irp.files.get()
        self.assertIsNone(f.answer)
        self.assertEqual(f.uploader, self.tfoms_user)

    def test_file_upload_attaches_to_answer(self):
        from django.core.files.uploadedfile import SimpleUploadedFile

        irp = self._make_irp()
        answer = irp.answers.create(
            user=self.tfoms_user, text="ответ", is_preliminary=False
        )
        self.client.force_login(self.tfoms_user)
        resp = self.client.post(
            reverse("journal:file", args=[irp.pk]),
            {
                "file": SimpleUploadedFile("reply.pdf", b"pdf"),
                "answer": answer.pk,
            },
        )
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(
            irp.files.get(answer=answer).file.name, f"journal/{irp.pk}/reply.pdf"
        )

    def test_file_upload_foreign_forbidden(self):
        from django.core.files.uploadedfile import SimpleUploadedFile

        other = self._make_irp(owner=self.tfoms_user)
        self.client.force_login(self.smo_user)
        resp = self.client.post(
            reverse("journal:file", args=[other.pk]),
            {"file": SimpleUploadedFile("doc.txt", b"x")},
        )
        self.assertEqual(resp.status_code, 403)

    def test_redirect_updates_route_and_history(self):
        irp = self._make_irp()
        self.client.force_login(self.tfoms_user)
        resp = self.client.post(
            reverse("journal:redirect", args=[irp.pk]),
            {
                "otv_t": 1,
                "otv_kon": 81007,
                "employee_it": self.tfoms_user.pk,
                "line_it": 1,
                "pr_out": 1,
                "date_cross": datetime.date.today().isoformat(),
                "time_cross": "12:00",
            },
        )
        self.assertEqual(resp.status_code, 302)
        irp.refresh_from_db()
        self.assertEqual(irp.otv_kon, 81007)
        self.assertEqual(irp.pr_out, 1)
        self.assertTrue(IrpHistory.objects.filter(irp=irp, field_name="pr_out").exists())

    def test_redirect_requires_login(self):
        irp = self._make_irp()
        resp = self.client.get(reverse("journal:redirect", args=[irp.pk]))
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/accounts/login", resp.url)

    def test_redirect_smo_foreign_forbidden(self):
        other = self._make_irp(owner=self.tfoms_user)
        self.client.force_login(self.smo_user)
        resp = self.client.get(reverse("journal:redirect", args=[other.pk]))
        self.assertEqual(resp.status_code, 403)

    def test_cover_letter_renders(self):
        irp = self._make_irp()
        self.client.force_login(self.tfoms_user)
        resp = self.client.get(reverse("journal:cover", args=[irp.pk]))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Сопроводительное письмо")
        self.assertContains(resp, "Прошу разобраться")

    def test_cover_letter_smo_foreign_forbidden(self):
        other = self._make_irp(owner=self.tfoms_user)
        self.client.force_login(self.smo_user)
        resp = self.client.get(reverse("journal:cover", args=[other.pk]))
        self.assertEqual(resp.status_code, 403)

    def test_detail_shows_answers_and_files(self):
        from django.core.files.uploadedfile import SimpleUploadedFile

        irp = self._make_irp()
        irp.answers.create(user=self.tfoms_user, text="Ответ на обращение")
        IrpFile.objects.create(
            irp=irp,
            file=SimpleUploadedFile("attach.txt", b"a"),
            uploader=self.tfoms_user,
        )
        self.client.force_login(self.tfoms_user)
        resp = self.client.get(reverse("journal:detail", args=[irp.pk]))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Ответ на обращение")
        self.assertContains(resp, "attach.txt")
        self.assertContains(resp, "Предварительный ответ")

"""Тесты journal: модели Irp и IrpTheme,(XmlFiles), а также экраны журнала.

Покрытие Этапа 2: RBAC-ограничение СМО, реестр, создание, редактирование,
история изменений.
"""

import datetime
import tempfile
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth.models import Group
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError, connection, transaction
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from apps.core.models import EventLog
from apps.core.roles import ensure_role_groups
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

    def _create_irp(self, date_close=None, data_plan=None, date_create=None):
        date_create = date_create or datetime.date.today()
        return Irp.objects.create(
            n_irp="00000000-0000-0000-0000-000000000001",
            irp_type=1,
            date_create=date_create,
            way=1,
            how=1,
            theme=self.theme,
            otv_t=1,
            otv_kon=81000,
            employee_one=self.employee,
            data_plan=data_plan or date_create + datetime.timedelta(days=30),
            z_f="Заявитель",
            date_close=date_close,
            result=2 if date_close else None,
            status=Irp.Status.CLOSED if date_close else Irp.Status.REGISTERED,
        )

    def test_is_closed(self):
        irp = self._create_irp(date_close=datetime.date.today())
        self.assertTrue(irp.is_closed)

    def test_is_overdue(self):
        yesterday = datetime.date.today() - datetime.timedelta(days=1)
        irp = self._create_irp(
            date_create=yesterday - datetime.timedelta(days=1), data_plan=yesterday
        )
        self.assertTrue(irp.is_overdue)

    def test_not_overdue_when_closed(self):
        yesterday = datetime.date.today() - datetime.timedelta(days=1)
        irp = self._create_irp(
            date_create=yesterday - datetime.timedelta(days=1),
            data_plan=yesterday,
            date_close=datetime.date.today(),
        )
        self.assertFalse(irp.is_overdue)

    def test_document_type_is_not_invented_when_omitted(self):
        irp = self._create_irp()
        self.assertIsNone(irp.z_doctype)

    def test_model_validation_rejects_plan_before_creation(self):
        irp = self._create_irp()
        irp.data_plan = irp.date_create - datetime.timedelta(days=1)

        with self.assertRaisesMessage(
            ValidationError, "Плановый срок не может быть раньше даты поступления"
        ):
            irp.full_clean()

    def test_database_rejects_invalid_status_and_dates(self):
        irp = self._create_irp()
        invalid_updates = (
            {"status": "unknown"},
            {"data_plan": irp.date_create - datetime.timedelta(days=1)},
        )
        for values in invalid_updates:
            with self.subTest(values=values), self.assertRaises(IntegrityError), transaction.atomic():
                Irp.objects.filter(pk=irp.pk).update(**values)

        with self.assertRaises(IntegrityError), transaction.atomic():
            Irp.objects.filter(pk=irp.pk).update(
                status=Irp.Status.CLOSED,
                result=2,
                date_close=irp.date_create - datetime.timedelta(days=1),
            )


class JournalScreenTests(TestCase):
    """Тесты экранов журнала (Этап 2)."""

    def setUp(self):
        ensure_role_groups()
        self.theme = IrpTheme.objects.create(
            code_name="ZZ.ZZ", title="Доступ", version=3
        )
        self.tfoms_user = Employee.objects.create_user(
            username="tfoms_op", password="GoodPass!1", org=81000
        )
        self.smo_user = Employee.objects.create_user(
            username="smo_agent", password="GoodPass!1", org=81001
        )
        self.tfoms_user.groups.add(Group.objects.get(name="ОП1"))
        self.smo_user.groups.add(Group.objects.get(name="СП1"))

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

    def test_list_denies_user_without_role(self):
        user = Employee.objects.create_user(
            username="journal_no_role", password="GoodPass!1", org=81000
        )
        self.client.force_login(user)
        self.assertEqual(self.client.get(reverse("journal:list")).status_code, 403)

    def test_list_shows_irp(self):
        irp = self._make_irp()
        self.client.force_login(self.tfoms_user)
        resp = self.client.get(reverse("journal:list"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Петров")
        self.assertContains(resp, f'data-href="{reverse("journal:detail", args=[irp.pk])}"')
        self.assertContains(resp, "table-row-link")
        self.assertContains(resp, reverse("journal:list_print"))
        self.assertContains(resp, 'class="data data--wide data--journal')
        self.assertContains(resp, 'class="group-row__label"')
        self.assertContains(resp, 'class="col-status"')
        self.assertContains(resp, 'data-label="Статус"')
        self.assertContains(resp, f'title="{irp.n_irp}"')
        self.assertContains(resp, f'…{irp.n_irp[-12:]}')
        self.assertTrue(
            EventLog.objects.filter(
                event_type=EventLog.EventType.VIEW,
                user=self.tfoms_user,
                target="journal:list",
            ).exists()
        )

        css = (settings.BASE_DIR / "static/css/portal.css").read_text()
        self.assertIn(".data--journal .col-status", css)
        self.assertIn("position: sticky", css)
        self.assertIn("right: 0", css)
        self.assertIn(".data--journal .group-row th", css)
        self.assertIn("width: fit-content", css)
        self.assertIn("border-left: 2px solid", css)
        self.assertIn("min-width: 1120px !important", css)
        self.assertIn("table.data .group-row th", css)
        self.assertIn(".data--journal thead { display: none; }", css)
        self.assertIn("content: attr(data-label)", css)
        self.assertNotIn("tbody tr:hover { background: color-mix(in srgb, var(--chip-green)", css)

    def test_suggest_runs_in_database_and_preserves_org_scope(self):
        own = self._make_irp(owner=self.smo_user)
        own.z_f = "АЛЕКСАНДР Свой"
        own.save(update_fields=["z_f"])
        foreign = self._make_irp(owner=self.tfoms_user)
        foreign.z_f = "АЛЕКСАНДР Чужой"
        foreign.save(update_fields=["z_f"])
        self.client.force_login(self.smo_user)

        with CaptureQueriesContext(connection) as captured:
            response = self.client.get(
                reverse("journal:suggest"), {"field": "z_f", "q": "александр"}
            )

        self.assertEqual(response.json()["suggestions"], ["АЛЕКСАНДР Свой"])
        journal_queries = [
            query["sql"].lower()
            for query in captured.captured_queries
            if "journal_irp" in query["sql"].lower()
        ]
        self.assertTrue(any("translate" in sql and "limit 8" in sql for sql in journal_queries))

    def test_print_list_preserves_filters_and_org_scope(self):
        own = self._make_irp(owner=self.smo_user)
        own.z_f = "Нужная"
        own.save(update_fields=["z_f"])
        hidden_by_filter = self._make_irp(owner=self.smo_user)
        hidden_by_filter.z_f = "Другая"
        hidden_by_filter.save(update_fields=["z_f"])
        foreign = self._make_irp(owner=self.tfoms_user)
        foreign.z_f = "Нужная"
        foreign.save(update_fields=["z_f"])

        self.client.force_login(self.smo_user)
        response = self.client.get(
            reverse("journal:list_print"), {"z_f": "Нужная"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "journal/irp_list_print.html")
        self.assertContains(response, own.n_irp)
        self.assertNotContains(response, hidden_by_filter.n_irp)
        self.assertNotContains(response, foreign.n_irp)
        self.assertContains(response, "лимит 500")

    def test_print_list_requires_journal_role(self):
        user = Employee.objects.create_user(
            username="print_no_role", password="GoodPass!1", org=81000
        )
        self.client.force_login(user)
        self.assertEqual(
            self.client.get(reverse("journal:list_print")).status_code,
            403,
        )

    def test_sort_links_preserve_filters_and_expose_direction(self):
        self._make_irp()
        self._make_irp()
        self.client.force_login(self.tfoms_user)
        with patch("apps.journal.views.PAGE_SIZE", 1):
            response = self.client.get(
                reverse("journal:list"),
                {
                    "z_f": "Петров",
                    "status": "open",
                    "sort": "date_create",
                    "page": 2,
                },
            )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'aria-sort="ascending"')
        self.assertContains(response, "z_f=%D0%9F%D0%B5%D1%82%D1%80%D0%BE%D0%B2")
        self.assertContains(response, "status=open")
        self.assertNotContains(response, "page=2")
        self.assertContains(response, "page=1")

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
        IrpHistory.objects.create(
            irp=irp,
            user=self.tfoms_user,
            field_name="status",
            old_value="",
            new_value="created",
        )
        self.client.force_login(self.tfoms_user)
        resp = self.client.get(reverse("journal:detail", args=[irp.pk]))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Петров")
        self.assertContains(resp, irp.get_irp_type_display())
        self.assertContains(resp, 'class="data" data-client-sort')
        self.assertTrue(
            EventLog.objects.filter(
                event_type=EventLog.EventType.VIEW,
                user=self.tfoms_user,
                target=f"irp:{irp.pk}:view",
            ).exists()
        )

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
                "result": 2,
            },
        )
        self.assertEqual(resp.status_code, 302)
        irp.refresh_from_db()
        self.assertEqual(irp.z_f, "Иванов")
        self.assertEqual(irp.status, Irp.Status.CLOSED)
        entry = IrpHistory.objects.filter(irp=irp, field_name="z_f").latest("id")
        self.assertEqual(entry.old_value, "Петров")
        self.assertEqual(entry.new_value, "Иванов")

    def test_smo_cannot_change_primary_owner_through_edit_post(self):
        irp = self._make_irp(owner=self.smo_user)
        self.client.force_login(self.smo_user)

        response = self.client.post(
            reverse("journal:edit", args=[irp.pk]),
            {
                "n_irp": irp.n_irp,
                "irp_type": 1,
                "date_create": irp.date_create.isoformat(),
                "way": 1,
                "how": 1,
                "theme": self.theme.pk,
                "otv_t": 1,
                "otv_kon": self.smo_user.org,
                "employee_one": self.tfoms_user.pk,
                "data_plan": irp.data_plan.isoformat(),
                "z_f": "Владелец сохранён",
            },
        )

        self.assertEqual(response.status_code, 302)
        irp.refresh_from_db()
        self.assertEqual(irp.employee_one, self.smo_user)
        self.assertEqual(irp.z_f, "Владелец сохранён")

    def test_smo_cannot_assign_foreign_organization_or_employee(self):
        irp = self._make_irp(owner=self.smo_user)
        foreign = Employee.objects.create_user(
            username="foreign_assignee", password="GoodPass!1", org=81007
        )
        self.client.force_login(self.smo_user)

        response = self.client.post(
            reverse("journal:edit", args=[irp.pk]),
            {
                "n_irp": irp.n_irp,
                "irp_type": 1,
                "date_create": irp.date_create.isoformat(),
                "way": 1,
                "how": 1,
                "theme": self.theme.pk,
                "otv_t": 1,
                "otv_kon": foreign.org,
                "employee_one": self.smo_user.pk,
                "employee_it": foreign.pk,
                "data_plan": irp.data_plan.isoformat(),
                "z_f": "Подмена scope",
            },
        )

        self.assertEqual(response.status_code, 200)
        irp.refresh_from_db()
        self.assertEqual(irp.otv_kon, self.smo_user.org)
        self.assertIsNone(irp.employee_it)
        self.assertEqual(irp.z_f, "Петров")

    def test_edit_clears_inapplicable_conditional_fields(self):
        irp = self._make_irp()
        irp.zh_d = "1"
        irp.pr_out = 1
        irp.date_cross = datetime.date.today()
        irp.time_cross = datetime.time(12, 0)
        irp.save()
        self.client.force_login(self.tfoms_user)

        response = self.client.post(
            reverse("journal:edit", args=[irp.pk]),
            {
                "n_irp": irp.n_irp,
                "irp_type": 1,
                "date_create": irp.date_create.isoformat(),
                "way": 1,
                "how": 1,
                "theme": self.theme.pk,
                "zh_d": "1",
                "otv_t": 1,
                "otv_kon": 81000,
                "employee_one": self.tfoms_user.pk,
                "data_plan": irp.data_plan.isoformat(),
                "date_cross": datetime.date.today().isoformat(),
                "time_cross": "12:00",
            },
        )

        self.assertEqual(response.status_code, 302)
        irp.refresh_from_db()
        self.assertIsNone(irp.zh_d)
        self.assertIsNone(irp.pr_out)
        self.assertIsNone(irp.date_cross)
        self.assertIsNone(irp.time_cross)

    def test_form_marks_conditional_fields_for_progressive_disclosure(self):
        self.client.force_login(self.tfoms_user)
        response = self.client.get(reverse("journal:create"))
        self.assertContains(response, 'data-conditional-controller="id_irp_type"')
        self.assertContains(response, 'data-conditional-controller="id_pr_out"', count=2)
        self.assertContains(response, "js/conditional-fields.js")

    def test_conditional_fields_css_can_override_field_layout(self):
        css = (settings.BASE_DIR / "static/css/portal.css").read_text()
        self.assertIn(".field[hidden] { display: none; }", css)

    def test_empty_insured_person_section_is_collapsed(self):
        self.client.force_login(self.tfoms_user)
        response = self.client.get(reverse("journal:create"))
        self.assertContains(response, '<details class="form-disclosure">')
        self.assertContains(response, "При необходимости")
        self.assertNotContains(response, 'value="14" selected')

    def test_populated_insured_person_section_is_open(self):
        irp = self._make_irp()
        irp.in_f = "Сидоров"
        irp.save(update_fields=["in_f"])
        self.client.force_login(self.tfoms_user)
        response = self.client.get(reverse("journal:edit", args=[irp.pk]))
        self.assertContains(response, '<details class="form-disclosure" open>')

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
        self.assertTrue(
            EventLog.objects.filter(
                event_type=EventLog.EventType.PRINT,
                target=f"irp:{irp.pk}:print",
            ).exists()
        )


@override_settings(MEDIA_ROOT=ROUTING_MEDIA_ROOT)
class RoutingTests(TestCase):
    """Этап 4: ответы (п. 215), файлы (п. 200), переадресация (п. 212)."""

    def setUp(self):
        ensure_role_groups()
        self.theme = IrpTheme.objects.create(
            code_name="RR.RR", title="Маршрутизация", version=3
        )
        self.tfoms_user = Employee.objects.create_user(
            username="routing_op", password="GoodPass!1", org=81000
        )
        self.smo_user = Employee.objects.create_user(
            username="routing_smo", password="GoodPass!1", org=81001
        )
        self.tfoms_user.groups.add(Group.objects.get(name="ОП1"))
        self.smo_user.groups.add(Group.objects.get(name="СП1"))

    def test_user_without_role_cannot_change_journal(self):
        unassigned = Employee.objects.create_user(
            username="no_role", password="GoodPass!1", org=81000
        )
        irp = self._make_irp()
        self.client.force_login(unassigned)
        response = self.client.post(
            reverse("journal:answer", args=[irp.pk]), {"text": "Недопустимо"}
        )
        self.assertEqual(response.status_code, 403)
        self.assertFalse(irp.answers.exists())

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
        irp.refresh_from_db()
        self.assertEqual(irp.status, Irp.Status.PRELIMINARY)
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

    def test_file_download_enforces_parent_irp_scope(self):
        irp = self._make_irp(owner=self.tfoms_user)
        attachment = IrpFile.objects.create(
            irp=irp,
            file=SimpleUploadedFile("private.txt", b"private"),
            uploader=self.tfoms_user,
        )
        self.client.force_login(self.smo_user)
        denied = self.client.get(reverse("journal:file_download", args=[attachment.pk]))
        self.assertEqual(denied.status_code, 403)
        self.assertFalse(
            EventLog.objects.filter(
                event_type=EventLog.EventType.EXPORT,
                target=f"irp:{irp.pk}:file:{attachment.pk}",
            ).exists()
        )
        self.client.force_login(self.tfoms_user)
        allowed = self.client.get(reverse("journal:file_download", args=[attachment.pk]))
        self.assertEqual(allowed.status_code, 200)
        self.assertEqual(b"".join(allowed.streaming_content), b"private")
        self.assertTrue(
            EventLog.objects.filter(
                event_type=EventLog.EventType.EXPORT,
                user=self.tfoms_user,
                target=f"irp:{irp.pk}:file:{attachment.pk}",
            ).exists()
        )

    def test_unavailable_attachment_returns_not_found_without_export_event(self):
        irp = self._make_irp(owner=self.tfoms_user)
        attachment = IrpFile.objects.create(
            irp=irp,
            file=SimpleUploadedFile("missing.txt", b"missing"),
            uploader=self.tfoms_user,
        )
        self.client.force_login(self.tfoms_user)

        with patch.object(
            attachment.file.storage, "open", side_effect=OSError("offline")
        ):
            response = self.client.get(
                reverse("journal:file_download", args=[attachment.pk])
            )

        self.assertEqual(response.status_code, 404)
        self.assertFalse(
            EventLog.objects.filter(
                event_type=EventLog.EventType.EXPORT,
                target=f"irp:{irp.pk}:file:{attachment.pk}",
            ).exists()
        )

    @override_settings(MEDIA_ROOT=ROUTING_MEDIA_ROOT)
    def test_deleting_irp_removes_cascaded_attachment_file(self):
        irp = self._make_irp(owner=self.tfoms_user)
        attachment = IrpFile.objects.create(
            irp=irp,
            file=SimpleUploadedFile("cascade-irp.txt", b"irp"),
            uploader=self.tfoms_user,
        )
        storage = attachment.file.storage
        name = attachment.file.name
        self.assertTrue(storage.exists(name))

        with self.captureOnCommitCallbacks(execute=True):
            irp.delete()

        self.assertFalse(storage.exists(name))

    def test_file_upload_rejects_unsafe_extension(self):
        from django.core.files.uploadedfile import SimpleUploadedFile

        irp = self._make_irp()
        self.client.force_login(self.tfoms_user)
        response = self.client.post(
            reverse("journal:file", args=[irp.pk]),
            {"file": SimpleUploadedFile("payload.php", b"<?php")},
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(irp.files.exists())
        self.assertContains(response, "Файл не прикреплён")

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
        self.assertEqual(irp.status, Irp.Status.REDIRECTED)
        self.assertTrue(IrpHistory.objects.filter(irp=irp, field_name="pr_out").exists())

    def test_closed_irp_is_terminal_for_mutations(self):
        irp = self._make_irp()
        irp.status = Irp.Status.CLOSED
        irp.date_close = datetime.date.today()
        irp.result = 2
        irp.save()
        self.client.force_login(self.tfoms_user)

        self.assertEqual(
            self.client.get(reverse("journal:edit", args=[irp.pk])).status_code, 403
        )
        self.assertEqual(
            self.client.post(
                reverse("journal:answer", args=[irp.pk]), {"text": "Поздний ответ"}
            ).status_code,
            403,
        )
        self.assertEqual(
            self.client.get(reverse("journal:redirect", args=[irp.pk])).status_code,
            403,
        )

    def test_close_requires_date_and_result_together(self):
        irp = self._make_irp()
        self.client.force_login(self.tfoms_user)
        response = self.client.post(
            reverse("journal:edit", args=[irp.pk]),
            {
                "n_irp": irp.n_irp,
                "irp_type": 1,
                "date_create": irp.date_create.isoformat(),
                "way": 1,
                "how": 1,
                "theme": self.theme.pk,
                "otv_t": 1,
                "otv_kon": 81000,
                "employee_one": self.tfoms_user.pk,
                "data_plan": irp.data_plan.isoformat(),
                "date_close": datetime.date.today().isoformat(),
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            "Для закрытия обращения одновременно укажите дату и исход.",
        )
        irp.refresh_from_db()
        self.assertEqual(irp.status, Irp.Status.REGISTERED)

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
        self.assertTrue(
            EventLog.objects.filter(
                event_type=EventLog.EventType.PRINT,
                target=f"irp:{irp.pk}:cover",
            ).exists()
        )

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

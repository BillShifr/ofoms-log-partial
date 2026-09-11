"""Тесты обмена и ФЛК (Этап 3):
XSD-валидация, импорт users*.xml / G1*.xml, Excel, протокол FLCP (0/41),
upsert по guid/n_irp, ограничение доступа к протоколам по организации.
"""

import errno
import os
import uuid
import zipfile
from concurrent.futures import ThreadPoolExecutor
from io import StringIO
from pathlib import Path
from threading import Barrier
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.contrib.auth.models import Group
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError, transaction
from django.test import TestCase, override_settings
from django.urls import reverse

from apps.core.roles import ensure_role_groups
from apps.employee.models import Employee
from apps.exchange.flc import FLCP_ERROR, build_flcp, error_result, ok_result
from apps.exchange.forms import UploadFileForm
from apps.exchange.importers import (
    SAFE_INTERNAL_IMPORT_ERROR,
    EmployeeXMLFile,
    ExcelIrpFile,
    IrpXMLFile,
    archive_artifact,
    validate_xlsx_container,
    write_unique_artifact,
)
from apps.exchange.models import ImportLog
from apps.journal.models import Irp, IrpTheme

SAMPLE_USERS = """<?xml version="1.0" encoding="windows-1251"?>
<USER_COLLECTION>
  <USERS>
    <USER_FULLNAME>Иванов Иван Иванович</USER_FULLNAME>
    <USER_UUID>00000000-0000-0000-0000-000000000001</USER_UUID>
    <USER_EMAIL>ivanov@example.ru</USER_EMAIL>
  </USERS>
  <USERS>
    <USER_FULLNAME>Петров Пётр Петрович</USER_FULLNAME>
    <USER_UUID>00000000-0000-0000-0000-000000000002</USER_UUID>
    <USER_EMAIL>petrov@example.ru</USER_EMAIL>
  </USERS>
</USER_COLLECTION>
""".encode("windows-1251")


def _irp_xml(theme_code: str, emp_guid: str, n_irp: str | None = None) -> bytes:
    return f"""<?xml version="1.0" encoding="windows-1251"?>
<IRP_LIST>
  <ZGLV>
    <filename>G1R_MMYYDDNNNN.xml</filename>
    <year>2026</year>
    <month>05</month>
    <day>14</day>
    <smo>81001</smo>
  </ZGLV>
  <IRP>
    <n_irp>{n_irp or uuid.uuid4()}</n_irp>
    <irp_type>1</irp_type>
    <date_create>2026-05-14</date_create>
    <way>1</way>
    <how>2</how>
    <theme>{theme_code}</theme>
    <otv_t>1</otv_t>
    <otv_kon>81000</otv_kon>
    <employee_1>{emp_guid}</employee_1>
    <data_plan>2026-06-13</data_plan>
    <z_sv>
      <z_f>Сидоров</z_f>
      <z_i>Сидор</z_i>
    </z_sv>
  </IRP>
</IRP_LIST>
""".encode("windows-1251")


class ExchangeTestMixin:
    def setUp(self):
        import tempfile

        ensure_role_groups()
        self.theme = IrpTheme.objects.create(
            code_name="TT.01", title="Тестовая тема", version=3
        )
        self.emp1 = Employee.objects.create_user(
            username="emp1", password="GoodPass!1", org=81000,
            guid=uuid.UUID("00000000-0000-0000-0000-000000000001"),
            first_name="Иван", last_name="Иванов", is_active=False,
        )
        self.tfoms = Employee.objects.create_user(
            username="tfoms", password="GoodPass!1", org=81000, is_superuser=True
        )
        self.smo = Employee.objects.create_user(
            username="smo", password="GoodPass!1", org=81001
        )
        self.smo.groups.add(Group.objects.get(name="СП1"))
        # Временные каталоги обмена (не трогаем рабочие exchange/)
        self.in_dir = tempfile.mkdtemp()
        self.out_dir = tempfile.mkdtemp()
        self.arch_dir = tempfile.mkdtemp()

    def _imp_kwargs(self):
        return {
            "in_dir": self.in_dir,
            "out_dir": self.out_dir,
            "archive_dir": self.arch_dir,
        }


class FlcTests(TestCase):
    def test_ok_result(self):
        r = ok_result("G1.xml", 3)
        self.assertEqual(r["OSHIB"], "0")
        self.assertIn("3", r["COMMENT"])

    def test_error_result(self):
        r = error_result("THEME", "Тема не из справочника", "abc")
        self.assertEqual(r["OSHIB"], "41")
        self.assertEqual(r["N_ZAP"], "abc")

    def test_build_flcp_windows1251(self):
        data = build_flcp("f.xml", [error_result("T", "тест", "1")])
        self.assertIn(b"windows-1251", data)


class ArtifactWriteTests(TestCase):
    def test_parallel_writers_never_share_or_overwrite_a_path(self):
        import tempfile

        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "G1R_same.xml"
            barrier = Barrier(2)

            def chunks(payload):
                barrier.wait(timeout=5)
                yield payload

            with ThreadPoolExecutor(max_workers=2) as executor:
                futures = [
                    executor.submit(write_unique_artifact, target, chunks(payload))
                    for payload in (b"first", b"second")
                ]
                paths = [future.result(timeout=5) for future in futures]

            self.assertEqual(len(set(paths)), 2)
            self.assertEqual(
                {path.read_bytes() for path in paths},
                {b"first", b"second"},
            )

    def test_failed_writer_removes_its_partial_artifact(self):
        import tempfile

        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "partial.xml"

            def failing_chunks():
                yield b"partial"
                raise RuntimeError("upload interrupted")

            with self.assertRaises(RuntimeError):
                write_unique_artifact(target, failing_chunks())

            self.assertFalse(target.exists())


class ImportLogConstraintTests(TestCase):
    def _assert_rejected(self, **overrides):
        values = {
            "org": 81000,
            "kind": ImportLog.Kind.IRP,
            "filename": "G1.xml",
            "status": ImportLog.Status.OK,
        }
        values.update(overrides)
        with self.assertRaises(IntegrityError), transaction.atomic():
            ImportLog.objects.create(**values)

    def test_unknown_organization_is_rejected_by_database(self):
        self._assert_rejected(org=99999)

    def test_unknown_import_kind_is_rejected_by_database(self):
        self._assert_rejected(kind="unknown")

    def test_unknown_import_status_is_rejected_by_database(self):
        self._assert_rejected(status="broken")

class EmployeeImportTests(ExchangeTestMixin, TestCase):
    def test_import_creates_users(self):
        from pathlib import Path

        path = Path(self.in_dir) / "users260514001.xml"
        path.write_bytes(SAMPLE_USERS)
        imp = EmployeeXMLFile(81000, path, **self._imp_kwargs())
        out = imp.process()
        self.assertTrue(out.ok)
        self.assertTrue(
            Employee.objects.filter(
                guid=uuid.UUID("00000000-0000-0000-0000-000000000002")
            ).exists()
        )
        # активность по умолчанию выключена (v1)
        self.assertFalse(self.emp1.is_active)
        # повторная загрузка (upsert) не плодит дубли
        path.write_bytes(SAMPLE_USERS)
        imp2 = EmployeeXMLFile(81000, path, **self._imp_kwargs())
        imp2.process()
        self.assertEqual(
            Employee.objects.filter(
                guid=uuid.UUID("00000000-0000-0000-0000-000000000002")
            ).count(),
            1,
        )


class IrpImportTests(ExchangeTestMixin, TestCase):
    def test_import_creates_irp_and_header(self):
        from pathlib import Path

        path = Path(self.in_dir) / "G1R_26051401.xml"
        path.write_bytes(_irp_xml("TT.01", str(self.emp1.guid)))
        imp = IrpXMLFile(81000, path, **self._imp_kwargs())
        out = imp.process()
        self.assertTrue(out.ok, out.errors)
        self.assertEqual(out.rows, 1)
        self.assertTrue(Irp.objects.filter(employee_one=self.emp1).exists())
        # заголовок сохранён в XmlFiles
        from apps.journal.models import XmlFiles

        self.assertEqual(XmlFiles.objects.count(), 1)

    def test_unknown_employee_rejected(self):
        from pathlib import Path

        path = Path(self.in_dir) / "G1R_26051402.xml"
        path.write_bytes(_irp_xml("TT.01", "00000000-0000-0000-0000-999999999999"))
        imp = IrpXMLFile(81000, path, **self._imp_kwargs())
        out = imp.process()
        self.assertFalse(out.ok)
        self.assertIn("41", [e["OSHIB"] for e in out.errors])
        self.assertEqual(Irp.objects.count(), 0)

    def test_unknown_theme_rejected(self):
        from pathlib import Path

        path = Path(self.in_dir) / "G1R_26051403.xml"
        path.write_bytes(_irp_xml("XX.NOPE", str(self.emp1.guid)))
        imp = IrpXMLFile(81000, path, **self._imp_kwargs())
        out = imp.process()
        self.assertFalse(out.ok)
        self.assertEqual(Irp.objects.count(), 0)

    def test_file_is_atomic_when_later_row_is_invalid(self):
        first_id = str(uuid.uuid4())
        second_id = str(uuid.uuid4())
        first = _irp_xml("TT.01", str(self.emp1.guid), first_id).decode("windows-1251")
        second_row = f"""
  <IRP>
    <n_irp>{second_id}</n_irp><irp_type>1</irp_type>
    <date_create>2026-05-14</date_create><way>1</way><how>2</how>
    <theme>XX.NOPE</theme><otv_t>1</otv_t><otv_kon>81000</otv_kon>
    <employee_1>{self.emp1.guid}</employee_1><data_plan>2026-06-13</data_plan>
    <z_sv><z_f>Ошибочный</z_f></z_sv>
  </IRP>
"""
        content = first.replace("</IRP_LIST>", second_row + "</IRP_LIST>").encode(
            "windows-1251"
        )
        path = Path(self.in_dir) / "G1R_atomic.xml"
        path.write_bytes(content)
        result = IrpXMLFile(81000, path, **self._imp_kwargs()).process()
        self.assertFalse(result.ok)
        self.assertEqual(result.rows, 0)
        self.assertFalse(Irp.objects.filter(n_irp__in=[first_id, second_id]).exists())
        from apps.journal.models import XmlFiles

        self.assertEqual(XmlFiles.objects.count(), 0)

    def test_unexpected_database_error_is_redacted_from_protocol(self):
        path = Path(self.in_dir) / "G1R_internal_error.xml"
        path.write_bytes(_irp_xml("TT.01", str(self.emp1.guid)))
        importer = IrpXMLFile(81000, path, **self._imp_kwargs())

        def mark_validated():
            importer.validated = True

        with patch.object(importer, "validate", side_effect=mark_validated), patch.object(
            importer,
            "load_db",
            side_effect=RuntimeError("password=secret host=/internal/db.sock"),
        ), patch("apps.exchange.importers.logger.exception") as log_exception:
            result = importer.process()

        self.assertFalse(result.ok)
        self.assertEqual(result.errors[0]["COMMENT"], SAFE_INTERNAL_IMPORT_ERROR)
        self.assertNotIn("secret", str(result.errors))
        self.assertNotIn("/internal", str(result.errors))
        log_exception.assert_called_once()

    def test_internal_schema_error_is_redacted_and_archived(self):
        path = Path(self.in_dir) / "G1R_missing_schema.xml"
        path.write_bytes(_irp_xml("TT.01", str(self.emp1.guid)))
        importer = IrpXMLFile(81000, path, **self._imp_kwargs())
        importer.xsd_name = "/internal/config/private-schema.xsd"

        with patch("apps.exchange.importers.logger.exception") as log_exception:
            result = importer.process()

        self.assertFalse(result.ok)
        self.assertEqual(result.errors[0]["COMMENT"], SAFE_INTERNAL_IMPORT_ERROR)
        self.assertNotIn("/internal", str(result.errors))
        self.assertFalse(path.exists())
        log_exception.assert_called_once()


class FlcValidationTests(ExchangeTestMixin, TestCase):
    def test_missing_required_field_reported(self):
        from apps.exchange.flc import validate_irp_record

        errors = validate_irp_record({"n_irp": "x"})
        self.assertGreater(len(errors), 0)
        fields = {e["IM_POL"] for e in errors}
        self.assertIn("IRP_TYPE", fields)
        self.assertIn("THEME", fields)

    def test_bad_reference_value_reported(self):
        from apps.exchange.flc import validate_irp_record

        errors = validate_irp_record(
            {
                "n_irp": "x",
                "irp_type": 99,
                "date_create": "2026-05-14",
                "way": 1,
                "how": 2,
                "theme": "TT.01",
                "otv_t": 1,
                "otv_kon": 81000,
                "data_plan": "2026-06-13",
                "employee_1": str(self.emp1.guid),
                "z_f": "Иванов",
            }
        )
        self.assertTrue(any(e["IM_POL"] == "IRP_TYPE" for e in errors))


class ExcelImportTests(ExchangeTestMixin, TestCase):
    def test_excel_import(self):
        from pathlib import Path

        from openpyxl import Workbook

        wb = Workbook()
        ws = wb.active
        ws.append(
            [
                "УНр", "Вид обращения", "Дата поступления", "Источник",
                "Способ", "Тема", "Тип ответств. организации",
                "Ответств. организация", "Принял (GUID)", "Плановая дата",
                "Фамилия",
            ]
        )
        ws.append(
            [
                str(uuid.uuid4()), 1, "2026-05-14", 1, 2, "TT.01", 1,
                81000, str(self.emp1.guid), "2026-06-13", "Петров",
            ]
        )
        path = Path(self.in_dir) / "import.xlsx"
        wb.save(path)
        imp = ExcelIrpFile(81000, path, **self._imp_kwargs())
        out = imp.process()
        self.assertTrue(out.ok, out.errors)
        self.assertEqual(out.rows, 1)
        self.assertTrue(Irp.objects.filter(z_f="Петров").exists())

    def test_xlsx_container_rejects_excessive_uncompressed_size(self):
        path = Path(self.in_dir) / "oversized-content.xlsx"
        with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("xl/worksheets/sheet1.xml", b"x" * 33)

        with patch(
            "apps.exchange.importers.MAX_XLSX_UNCOMPRESSED_SIZE", 32
        ), self.assertRaisesMessage(ValueError, "Распакованный XLSX"):
            validate_xlsx_container(path)

    def test_xlsx_container_rejects_excessive_member_count(self):
        path = Path(self.in_dir) / "many-members.xlsx"
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("one.xml", b"1")
            archive.writestr("two.xml", b"2")

        with patch(
            "apps.exchange.importers.MAX_XLSX_MEMBERS", 1
        ), self.assertRaisesMessage(ValueError, "слишком много"):
            validate_xlsx_container(path)

    def test_xlsx_container_rejects_unsafe_internal_path(self):
        path = Path(self.in_dir) / "unsafe-path.xlsx"
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("../outside.xml", b"x")

        with self.assertRaisesMessage(ValueError, "небезопасный внутренний путь"):
            validate_xlsx_container(path)

    def test_xlsx_container_rejects_invalid_zip(self):
        path = Path(self.in_dir) / "broken.xlsx"
        path.write_bytes(b"not-a-zip")

        with self.assertRaisesMessage(ValueError, "Повреждённый XLSX"):
            validate_xlsx_container(path)

    def test_xlsx_container_rejects_encrypted_member(self):
        archive = MagicMock()
        archive.__enter__.return_value.infolist.return_value = [
            SimpleNamespace(filename="xl/workbook.xml", flag_bits=0x1, file_size=10)
        ]

        with patch(
            "apps.exchange.importers.zipfile.ZipFile", return_value=archive
        ), self.assertRaisesMessage(ValueError, "Зашифрованные XLSX"):
            validate_xlsx_container(Path("encrypted.xlsx"))

    def test_excel_import_reports_container_limit_without_database_changes(self):
        from openpyxl import Workbook

        workbook = Workbook()
        workbook.active.append(["УНр"])
        path = Path(self.in_dir) / "limited.xlsx"
        workbook.save(path)
        importer = ExcelIrpFile(81000, path, **self._imp_kwargs())

        with patch("apps.exchange.importers.MAX_XLSX_UNCOMPRESSED_SIZE", 1):
            result = importer.process()

        self.assertFalse(result.ok)
        self.assertEqual(result.rows, 0)
        self.assertTrue(any("Распакованный XLSX" in str(error) for error in result.errors))
        self.assertFalse(Irp.objects.exists())
        self.assertFalse(path.exists())


class UploadScreenTests(ExchangeTestMixin, TestCase):
    def test_upload_requires_login(self):
        resp = self.client.get(reverse("exchange:upload"))
        self.assertEqual(resp.status_code, 302)

    def test_user_without_role_cannot_open_upload(self):
        user = Employee.objects.create_user(
            username="exchange_no_role", password="GoodPass!1", org=81000
        )
        self.client.force_login(user)
        self.assertEqual(self.client.get(reverse("exchange:upload")).status_code, 403)

    def test_upload_guidance_matches_server_contract(self):
        self.client.force_login(self.tfoms)
        response = self.client.get(reverse("exchange:upload"))

        self.assertContains(response, 'data-max-file-size="20971520"')
        self.assertContains(response, 'accept=".xml,.xlsx"')
        self.assertNotContains(response, ".xlsx,.xls")
        self.assertContains(response, "XLSX, не более 20 МБ")
        self.assertNotContains(response, "не более 10 МБ")

    def test_user_without_role_cannot_read_exchange(self):
        user = Employee.objects.create_user(
            username="exchange_reader_no_role", password="GoodPass!1", org=81000
        )
        log = ImportLog.objects.create(
            org=81000, kind="irp", filename="denied.xml", status="ok", rows=0
        )
        self.client.force_login(user)
        self.assertEqual(self.client.get(reverse("exchange:logs")).status_code, 403)
        self.assertEqual(
            self.client.get(reverse("exchange:protocol", args=[log.pk])).status_code,
            403,
        )

    def test_smo_sees_only_own_logs(self):
        ImportLog.objects.create(
            org=81001, kind="irp", filename="a.xml", status="ok", rows=1
        )
        ImportLog.objects.create(
            org=81000, kind="irp", filename="b.xml", status="error", rows=0
        )
        self.client.force_login(self.smo)
        resp = self.client.get(reverse("exchange:logs"))
        self.assertContains(resp, "a.xml")
        self.assertNotContains(resp, "b.xml")

    def test_smo_cannot_open_foreign_protocol(self):
        log = ImportLog.objects.create(
            org=81000, kind="irp", filename="b.xml",
            status="error", rows=0, flcp="",
        )
        self.client.force_login(self.smo)
        resp = self.client.get(reverse("exchange:protocol", args=[log.pk]))
        self.assertEqual(resp.status_code, 403)


class UploadPostTests(ExchangeTestMixin, TestCase):
    """POST-загрузка файла: запись в in/, обработка, FLCP в out/, ImportLog."""

    def setUp(self):
        super().setUp()
        self.client.force_login(self.tfoms)
        self._in = Path(self.in_dir)
        self._out = Path(self.out_dir)
        self._arch = Path(self.arch_dir)

    def _post(self, content: bytes, name: str):
        from django.core.files.uploadedfile import SimpleUploadedFile

        with override_settings(
            EXCHANGE_IN=self._in,
            EXCHANGE_OUT=self._out,
            EXCHANGE_ARCHIVE=self._arch,
        ):
            return self.client.post(
                reverse("exchange:upload"),
                {
                    "org": "81000",
                    "file": SimpleUploadedFile(name, content),
                },
            )

    def test_upload_valid_users_file(self):
        resp = self._post(SAMPLE_USERS, "users260514001.xml")
        self.assertEqual(resp.status_code, 302)
        log = ImportLog.objects.get(kind="users")
        self.assertEqual(log.status, ImportLog.Status.OK)
        self.assertTrue(log.flcp)
        self.assertTrue((self._out / "81000" / "users260514001.xml").exists())
        self.assertTrue(
            (self._arch / "81000" / "users260514001.xml").exists()
        )
        # два пользователя загружены (новый + обновлённый по GUID)
        self.assertEqual(Employee.objects.count(), 4)  # 2 фикстуры + 2 из файла

    def test_upload_valid_g1_file(self):
        resp = self._post(
            _irp_xml("TT.01", str(self.emp1.guid)), "G1R_26051401.xml"
        )
        self.assertEqual(resp.status_code, 302)
        log = ImportLog.objects.get(kind="irp")
        self.assertEqual(log.status, ImportLog.Status.OK)
        self.assertEqual(log.rows, 1)
        self.assertTrue(Irp.objects.filter(employee_one=self.emp1).exists())

    def test_upload_invalid_extension_returns_form_error(self):
        resp = self._post(b"data", "note.txt")
        self.assertEqual(resp.status_code, 200)  # ошибка формы, не 500
        self.assertContains(resp, "Неизвестный тип файла")

    def test_upload_rejects_declared_oversize_before_writing(self):
        oversized = SimpleUploadedFile(
            "G1R_large.xml", b"x", content_type="application/xml"
        )
        oversized.size = 20 * 1024 * 1024 + 1
        form = UploadFileForm(
            data={"org": "81000"},
            files={"file": oversized},
            org_choices=[(81000, "ТФОМС")],
        )
        self.assertFalse(form.is_valid())
        self.assertIn("Размер файла не должен превышать 20 МБ", str(form.errors))
        self.assertFalse((self._in / "81000" / "G1R_large.xml").exists())

    def test_repeated_upload_does_not_overwrite_archive_or_protocol(self):
        self._post(SAMPLE_USERS, "users260514001.xml")
        self._post(SAMPLE_USERS, "users260514001.xml")
        archived = list((self._arch / "81000").glob("users260514001*"))
        protocols = list((self._out / "81000").glob("users260514001*"))
        self.assertEqual(len(archived), 2)
        self.assertEqual(len(protocols), 2)

    def test_upload_rejects_smo_foreign_org(self):
        self.client.force_login(self.smo)
        resp = self.client.get(reverse("exchange:upload"))
        form = resp.context["form"]
        self.assertNotIn("81000", [c[0] for c in form.fields["org"].choices])


class ImportCommandTests(ExchangeTestMixin, TestCase):
    """Автозагрузка import_exchange из каталога exchange/in (Cron/systemd)."""

    def test_auto_import_creates_logs_and_flcp(self):
        from django.core.management import call_command

        in_dir = Path(self.in_dir)
        out_dir = Path(self.out_dir)
        arch_dir = Path(self.arch_dir)

        (in_dir / "81000").mkdir(parents=True, exist_ok=True)
        (in_dir / "81000" / "users260514002.xml").write_bytes(SAMPLE_USERS)

        with override_settings(
            EXCHANGE_IN=in_dir,
            EXCHANGE_OUT=out_dir,
            EXCHANGE_ARCHIVE=arch_dir,
        ):
            call_command("import_exchange", orgs=[81000], verbosity=0)

        log = ImportLog.objects.get(kind="users")
        self.assertEqual(log.status, ImportLog.Status.OK)
        self.assertTrue((out_dir / "81000" / "users260514002.xml").exists())
        self.assertTrue((arch_dir / "81000" / "users260514002.xml").exists())
        self.assertEqual(Employee.objects.count(), 4)

    def test_cross_filesystem_archive_removes_source_and_prevents_reimport(self):
        from django.core.management import call_command

        in_dir = Path(self.in_dir)
        out_dir = Path(self.out_dir)
        arch_dir = Path(self.arch_dir)
        source = in_dir / "81000" / "users260514003.xml"
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_bytes(SAMPLE_USERS)

        exchange_settings = {
            "EXCHANGE_IN": in_dir,
            "EXCHANGE_OUT": out_dir,
            "EXCHANGE_ARCHIVE": arch_dir,
        }
        with override_settings(**exchange_settings), patch(
            "apps.exchange.importers.os.replace",
            side_effect=OSError(errno.EXDEV, "cross-device link"),
        ):
            call_command("import_exchange", orgs=[81000], verbosity=0)

        self.assertFalse(source.exists())
        archived = arch_dir / "81000" / source.name
        self.assertEqual(archived.read_bytes(), SAMPLE_USERS)
        self.assertEqual(ImportLog.objects.filter(filename=source.name).count(), 1)

        output = StringIO()
        with override_settings(**exchange_settings):
            call_command("import_exchange", orgs=[81000], stdout=output)
        self.assertIn("Файлов для обработки не найдено", output.getvalue())
        self.assertEqual(ImportLog.objects.filter(filename=source.name).count(), 1)

    def test_archive_does_not_mask_non_cross_filesystem_error(self):
        source = Path(self.in_dir) / "protected.xml"
        source.write_bytes(b"source")

        with patch(
            "apps.exchange.importers.os.replace",
            side_effect=PermissionError(errno.EACCES, "permission denied"),
        ), patch("apps.exchange.importers.shutil.copy2") as copy_file, self.assertRaises(
            PermissionError
        ):
            archive_artifact(source, Path(self.arch_dir), 81000)

        copy_file.assert_not_called()
        self.assertTrue(source.exists())

    def test_parallel_archives_never_overwrite_the_same_destination(self):
        source_dirs = [Path(self.in_dir) / "first", Path(self.in_dir) / "second"]
        sources = []
        for source_dir, payload in zip(source_dirs, (b"first", b"second"), strict=True):
            source_dir.mkdir()
            source = source_dir / "G1R_same.xml"
            source.write_bytes(payload)
            sources.append(source)

        barrier = Barrier(2)
        real_replace = os.replace

        def synchronized_replace(source, destination):
            barrier.wait(timeout=5)
            return real_replace(source, destination)

        with patch(
            "apps.exchange.importers.os.replace",
            side_effect=synchronized_replace,
        ), ThreadPoolExecutor(max_workers=2) as executor:
            futures = [
                executor.submit(
                    archive_artifact,
                    source,
                    Path(self.arch_dir),
                    81000,
                )
                for source in sources
            ]
            destinations = [future.result(timeout=5) for future in futures]

        self.assertEqual(len(set(destinations)), 2)
        self.assertEqual(
            {destination.read_bytes() for destination in destinations},
            {b"first", b"second"},
        )
        self.assertFalse(any(source.exists() for source in sources))


class XsdValidationTests(ExchangeTestMixin, TestCase):
    """XSD-валидация отбивает структурно неверные файлы с протоколом 41."""

    def test_schema_invalid_g1_rejected(self):
        bad = b"""<?xml version="1.0" encoding="windows-1251"?>
<IRP_LIST>
  <IRP>
    <n_irp>xxx</n_irp>
  </IRP>
</IRP_LIST>"""
        path = Path(self.in_dir) / "G1R_26051499.xml"
        path.write_bytes(bad)
        imp = IrpXMLFile(81000, path, **self._imp_kwargs())
        out = imp.process()
        self.assertFalse(out.validated)
        self.assertEqual(out.errors[0]["OSHIB"], FLCP_ERROR)
        self.assertEqual(Irp.objects.count(), 0)

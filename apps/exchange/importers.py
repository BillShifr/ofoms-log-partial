"""Импорт файлов обмена (Этап 3).

Порт v1 (journal.portal.tfoms/load_emploees.py) с улучшениями:
- dataclass ImportResult вместо голых print/атрибутов;
- пути каталогов и XSD берутся из настроек (допустимо переопределение в тестах);
- единый ФЛК (apps.exchange.flc) для XML и Excel;
- записи протокола (ImportLog) сохраняются в БД.
"""

import errno
import glob
import logging
import os
import shutil
import stat
import zipfile
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db import IntegrityError, transaction
from lxml import etree

from apps.core.models import EventLog, log_event
from apps.employee.models import Employee
from apps.exchange import flc
from apps.exchange.models import ImportLog
from apps.journal.models import Irp, IrpHistory, IrpTheme, XmlFiles

XSD_DIR = Path(__file__).resolve().parent / "xsd"
MAX_EXCHANGE_FILE_SIZE = 20 * 1024 * 1024
MAX_XLSX_UNCOMPRESSED_SIZE = 100 * 1024 * 1024
MAX_XLSX_MEMBERS = 1000
SAFE_INTERNAL_IMPORT_ERROR = (
    "Внутренняя ошибка обработки файла. Обратитесь к администратору."
)

logger = logging.getLogger(__name__)


class ArtifactRollback:
    """Удаляет созданные exchange artifacts при сбое окружающей операции."""

    def __init__(self):
        self.paths: list[Path] = []
        self.moves: list[tuple[Path, Path]] = []

    def track(self, path: Path | None) -> None:
        if path is not None:
            self.paths.append(Path(path))

    def restore_on_failure(self, current: Path | None, original: Path) -> None:
        if current is not None:
            self.moves.append((Path(current), Path(original)))

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        if exc_type is None:
            return False
        for path in reversed(self.paths):
            try:
                path.unlink(missing_ok=True)
            except OSError:
                logger.exception("Failed to roll back exchange artifact %s", path.name)
        for current, original in reversed(self.moves):
            if not current.exists():
                continue
            try:
                os.replace(current, original)
            except OSError as error:
                if error.errno != errno.EXDEV:
                    logger.exception(
                        "Failed to restore exchange input %s", original.name
                    )
                    continue
                try:
                    shutil.copy2(current, original)
                    current.unlink()
                except OSError:
                    original.unlink(missing_ok=True)
                    logger.exception(
                        "Failed to restore cross-filesystem exchange input %s",
                        original.name,
                    )
        return False


def ensure_private_directory(path: Path) -> None:
    """Создаёт/нормализует каталог artifacts для единственного runtime UID."""
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.chmod(0o700)


def _open_private_exclusive(path: Path):
    descriptor = os.open(
        path,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL,
        0o600,
    )
    try:
        os.fchmod(descriptor, 0o600)
    except BaseException:
        os.close(descriptor)
        path.unlink(missing_ok=True)
        raise
    return os.fdopen(descriptor, "wb")


def validate_xlsx_container(path: Path) -> None:
    """Отклоняет опасный ZIP-контейнер до передачи XLSX в openpyxl."""
    try:
        with zipfile.ZipFile(path) as archive:
            members = archive.infolist()
    except zipfile.BadZipFile as error:
        raise ValueError("Повреждённый XLSX-контейнер") from error

    if len(members) > MAX_XLSX_MEMBERS:
        raise ValueError("XLSX содержит слишком много внутренних файлов")

    uncompressed_size = 0
    for member in members:
        member_path = PurePosixPath(member.filename.replace("\\", "/"))
        if member_path.is_absolute() or ".." in member_path.parts:
            raise ValueError("XLSX содержит небезопасный внутренний путь")
        if member.flag_bits & 0x1:
            raise ValueError("Зашифрованные XLSX не поддерживаются")
        uncompressed_size += member.file_size
        if uncompressed_size > MAX_XLSX_UNCOMPRESSED_SIZE:
            raise ValueError("Распакованный XLSX превышает 100 МБ")


def validate_regular_exchange_input(path: Path) -> None:
    """Разрешает importer только отдельный обычный filesystem object."""
    try:
        file_stat = path.lstat()
    except OSError as error:
        raise ValueError("Входной файл недоступен") from error
    if not stat.S_ISREG(file_stat.st_mode) or file_stat.st_nlink != 1:
        raise ValueError("Входной объект должен быть обычным файлом; ссылки запрещены")


def write_unique_artifact(path: Path, chunks) -> Path:
    """Атомарно создаёт новый artifact, не перезаписывая параллельный файл."""
    import uuid

    ensure_private_directory(path.parent)
    candidate = path
    while True:
        try:
            with _open_private_exclusive(candidate) as artifact:
                for chunk in chunks:
                    artifact.write(chunk)
            return candidate
        except FileExistsError:
            candidate = path.with_name(
                f"{path.stem}-{uuid.uuid4().hex[:8]}{path.suffix}"
            )
        except BaseException:
            candidate.unlink(missing_ok=True)
            raise


def reserve_unique_artifact_path(path: Path) -> Path:
    """Атомарно резервирует свободное имя пустым файлом текущего процесса."""
    import uuid

    ensure_private_directory(path.parent)
    candidate = path
    while True:
        try:
            with _open_private_exclusive(candidate):
                pass
            return candidate
        except FileExistsError:
            candidate = path.with_name(
                f"{path.stem}-{uuid.uuid4().hex[:8]}{path.suffix}"
            )


def archive_artifact(source: Path, archive_dir: Path, org: int) -> Path:
    """Move a processed input exactly once, including across filesystems."""
    source_stat = source.lstat()
    is_exclusive_regular = (
        stat.S_ISREG(source_stat.st_mode) and source_stat.st_nlink == 1
    )
    if is_exclusive_regular:
        source.chmod(0o600)
    org_dir = archive_dir / str(org)
    destination = reserve_unique_artifact_path(org_dir / source.name)
    if not is_exclusive_regular:
        source.unlink()
        return destination
    try:
        os.replace(source, destination)
    except OSError as exc:
        if exc.errno == errno.EXDEV:
            try:
                shutil.copy2(source, destination)
                source.unlink()
            except BaseException:
                destination.unlink(missing_ok=True)
                raise
        else:
            destination.unlink(missing_ok=True)
            raise
    return destination


@dataclass
class ImportResult:
    """Результат обработки одного файла (для протокола FLCP и журнала)."""

    filename: str
    org: int
    kind: str
    errors: list = field(default_factory=list)
    rows: int = 0
    validated: bool = False

    @property
    def ok(self) -> bool:
        return not self.errors

    def flcp_bytes(self) -> bytes:
        errors = list(self.errors)
        if not errors:
            errors = [flc.ok_result(self.filename, self.rows)]
        return flc.build_flcp(self.filename, errors)


def eget(e, text):
    """Значение вложенного элемента XML или None (v1)."""
    try:
        node = e.find(text)
        return node.text if node is not None else None
    except Exception:
        return None


def elem2dict(node):
    """Lxml-узел -> dict (v1): имена тегов в нижнем регистре, вложения — dict."""
    if node is None:
        return None
    d: dict = {}
    for e in node.iterchildren():
        key = (e.tag.split("}")[1] if "}" in e.tag else e.tag).lower()
        if e.text and e.text.strip():
            value = e.text.strip()
        else:
            value = elem2dict(e)
        d[key] = value
    return d


class XsdExchangeFile:
    """Базовая обработка файла: XSD-валидация -> загрузка в БД -> FLCP."""

    kind = "xml"
    xsd_name: str = ""
    org: int
    real_file: Path

    def __init__(self, org, filepath, in_dir=None, out_dir=None, archive_dir=None):
        self.org = int(org)
        self.real_file = Path(filepath)
        self.basename = self.real_file.name
        self.errors: list = []
        self.rows = 0
        self.validated = False
        self.xml = None
        self.archived_path: Path | None = None
        self._in_dir = Path(in_dir or settings.EXCHANGE_IN)
        self._out_dir = Path(out_dir or settings.EXCHANGE_OUT)
        self._archive_dir = Path(archive_dir or settings.EXCHANGE_ARCHIVE)

    # -- этапы обработки ----------------------------------------------------

    def validate(self):
        """XSD-валидация и разбор XML."""
        try:
            validate_regular_exchange_input(self.real_file)
            if self.real_file.stat().st_size > MAX_EXCHANGE_FILE_SIZE:
                self.errors.append(
                    flc.error_result("FILE", "Размер файла превышает 20 МБ")
                )
                return
            schema_path = Path(self.xsd_name)
            if not schema_path.is_absolute():
                schema_path = XSD_DIR / schema_path
            with open(schema_path, "rb") as f:
                schema = etree.XMLSchema(etree.XML(f.read()))
            parser = etree.XMLParser(
                schema=schema,
                resolve_entities=False,
                no_network=True,
                huge_tree=False,
            )
            with open(self.real_file, "rb") as f:
                self.xml = etree.parse(f, parser).getroot()
            self.validated = True
        except ValueError as exc:
            self.errors.append(flc.error_result("FILE", str(exc)))
        except (etree.XMLSyntaxError, etree.DocumentInvalid) as exc:
            self.errors.append(flc.error_result("XML", str(exc)))
        except Exception:  # noqa: BLE001 -- redact internal parser/config details
            logger.exception(
                "Unexpected XML import validation failure for %s (org=%s)",
                self.basename,
                self.org,
            )
            self.errors.append(flc.error_result("XML", SAFE_INTERNAL_IMPORT_ERROR))

    def load_db(self):
        raise NotImplementedError

    def process(self) -> ImportResult:
        """Полный цикл: валидация, загрузка, архив, протокол."""
        self.validate()
        if self.validated:
            try:
                with transaction.atomic():
                    self.load_db()
                    if self.errors:
                        transaction.set_rollback(True)
            except Exception:  # noqa: BLE001 -- log details, expose stable FLCP error
                logger.exception(
                    "Unexpected database import failure for %s (org=%s)",
                    self.basename,
                    self.org,
                )
                self.errors.append(
                    flc.error_result("IMPORT", SAFE_INTERNAL_IMPORT_ERROR)
                )
            if self.errors:
                self.rows = 0
        self.archived_path = self._archive()
        return ImportResult(
            filename=self.basename,
            org=self.org,
            kind=self.kind,
            errors=list(self.errors),
            rows=self.rows,
            validated=self.validated,
        )

    # -- каталоги -----------------------------------------------------------

    def _archive(self):
        return archive_artifact(self.real_file, self._archive_dir, self.org)

    def write_flcp(self, result: ImportResult) -> Path:
        org_dir = self._out_dir / str(self.org)
        return write_unique_artifact(
            org_dir / self.basename,
            (result.flcp_bytes(),),
        )


class EmployeeXMLFile(XsdExchangeFile):
    """Импорт сотрудников users*.xml (upsert по GUID, v1 load_emploees)."""

    kind = "users"
    xsd_name = "USERSMMYYDDNNN.xsd"
    mask = "users*.xml"

    def load_db(self):
        if self.xml is None:
            return
        for user in self.xml.xpath("//USER_COLLECTION/USERS"):
            fullname_raw = eget(user, "USER_FULLNAME")
            fullname = (fullname_raw or "").strip()
            guid_raw = eget(user, "USER_UUID")
            guid = (guid_raw or "").strip()
            email_raw = eget(user, "USER_EMAIL")
            email = None
            if email_raw:
                try:
                    validate_email(email_raw.strip())
                    email = email_raw.strip()
                except ValidationError:
                    self.errors.append(
                        flc.error_result("USER_EMAIL", "Некорректный e-mail", guid)
                    )

            rec = {
                "USER_FULLNAME": fullname,
                "USER_UUID": guid,
                "USER_EMAIL": email or "",
            }
            flc_errors = flc.validate_users_record(rec)
            if flc_errors:
                self.errors.extend(flc_errors)
                continue

            lname = fullname.split(" ")[0][:29].strip()
            fname = fullname.split(" ")[-1][:29].strip()

            _upsert_employee(
                guid=guid,
                fname=fname,
                lname=lname,
                email=email,
                org=self.org,
            )
            self.rows += 1


def _make_username(
    fname: str,
    lname: str,
    email: str | None,
    *,
    with_suffix: bool = False,
) -> str:
    """Формирует bounded username; уникальность окончательно проверяет БД."""
    import uuid

    from pytils.translit import slugify

    if email:
        username = slugify(email.split("@", 1)[0])[:25]
    else:
        username = slugify(lname + fname[:1])
    if not username:
        username = uuid.uuid4().hex[:10]
    if with_suffix:
        username = f"{username[:145]}_{uuid.uuid4().hex[:4]}"
    return username[:150]


def _upsert_employee(*, guid, fname: str, lname: str, email: str | None, org: int):
    """Сериализует GUID-upsert и повторяет только подтверждённый username conflict."""
    existing = Employee.objects.filter(guid=guid).first()
    if existing is not None:
        if existing.last_name != lname or existing.first_name != fname:
            existing.last_name = lname
            existing.first_name = fname
            existing.save(update_fields=["last_name", "first_name"])
        return existing

    for attempt in range(20):
        username = _make_username(fname, lname, email, with_suffix=attempt > 0)
        try:
            with transaction.atomic():
                return Employee.objects.create_user(
                    username=username,
                    guid=guid,
                    email=email,
                    first_name=fname,
                    last_name=lname,
                    is_active=False,
                    org=org,
                )
        except IntegrityError:
            existing = Employee.objects.filter(guid=guid).first()
            if existing is not None:
                if existing.last_name != lname or existing.first_name != fname:
                    existing.last_name = lname
                    existing.first_name = fname
                    existing.save(update_fields=["last_name", "first_name"])
                return existing
            if not Employee.objects.filter(username=username).exists():
                raise
    raise RuntimeError("Не удалось выделить уникальное имя импортируемому сотруднику")


class IrpXMLFile(XsdExchangeFile):
    """Импорт обращений G1*.xml (upsert по n_irp)."""

    kind = "irp"
    xsd_name = "G1R_MMYYDDNNNN.xsd"
    mask = "G1*.xml"

    def load_db(self):
        if self.xml is None:
            return
        input_file = self._load_header()
        if input_file is None:
            return
        for node in self.xml.xpath("//IRP_LIST/IRP"):
            d = elem2dict(node)
            self._import_one(d, input_file=input_file)

    def _load_header(self):
        """Заголовок ZGLV -> XmlFiles (метаданные файла)."""
        nodes = self.xml.xpath("//IRP_LIST/ZGLV")
        if not nodes:
            self.errors.append(flc.error_result("ZGLV", "Отсутствует блок ZGLV"))
            return
        header = elem2dict(nodes[0])
        header["real_filename"] = str(self.real_file)
        header.setdefault("filename", self.basename)
        try:
            header_org = int(header.get("smo"))
        except (TypeError, ValueError):
            header_org = None
        if header_org != self.org:
            self.errors.append(
                flc.error_result(
                    "SMO",
                    "Организация в заголовке не соответствует каналу загрузки",
                    "ZGLV",
                )
            )
            return None
        x = XmlFiles(**header)
        try:
            x.full_clean()
            x.save()
            return x
        except ValidationError as e:
            for key, msgs in e.message_dict.items():
                self.errors.append(
                    flc.error_result(str(key).upper(), str(msgs), "ZGLV")
                )
            return None

    def _import_one(self, d: dict, *, input_file: XmlFiles):
        """Валидация ФЛК записи + upsert (v1 load_emploees.py)."""
        for block in ("z_sv", "in_sv"):
            if block in d and isinstance(d.get(block), dict):
                d.update(d.pop(block))
        if "e-mail" in d:
            d["e_mail"] = d.pop("e-mail")

        # Сотрудник, принявший обращение (обязателен)
        e_one = d.get("employee_1")
        employee_one = Employee.objects.filter(guid=e_one).first()
        if not employee_one:
            self.errors.append(
                flc.error_result(
                    "EMPLOYEE_1", f"Неизвестный сотрудник с GUID {e_one}", d.get("n_irp")
                )
            )
            return
        if employee_one.org != self.org:
            self.errors.append(
                flc.error_result(
                    "EMPLOYEE_1",
                    "Сотрудник не относится к организации-отправителю",
                    d.get("n_irp"),
                )
            )
            return

        # Ответственный сотрудник (необязателен)
        employee_it = None
        e_it = d.get("employee_it")
        if e_it:
            employee_it = Employee.objects.filter(guid=e_it).first()
            if not employee_it:
                self.errors.append(
                    flc.error_result(
                        "EMPLOYEE_IT",
                        f"Неизвестный сотрудник с GUID {e_it}",
                        d.get("n_irp"),
                    )
                )
                return

        theme_txt = d.get("theme")
        theme = (
            IrpTheme.objects.filter(code_name=str(theme_txt), version=3).first()
            if theme_txt
            else None
        )

        d = _normalize_irp_fields(d)
        if "theme" in d:
            del d["theme"]
        if "employee_1" in d:
            del d["employee_1"]
        if "employee_it" in d:
            del d["employee_it"]

        flc_errors = flc.validate_irp_record(
            {**d, "theme": theme_txt, "employee_1": e_one, "employee_it": e_it}
        )
        if flc_errors:
            self.errors.extend(flc_errors)
            return

        try:
            _upsert_imported_irp(
                values=d,
                employee_one=employee_one,
                employee_it=employee_it,
                theme=theme,
                input_file=input_file,
                source_label=input_file.real_filename,
            )
        except ValidationError as e:
            for key, msgs in e.message_dict.items():
                self.errors.append(
                    flc.error_result(str(key).upper(), str(msgs), d["n_irp"])
                )
            return
        self.rows += 1


def _upsert_imported_irp(
    *, values, employee_one, employee_it, theme, input_file, source_label
):
    """Сериализует update и разрешает конкурентный insert по `n_irp`."""
    n_irp = values["n_irp"]
    for _ in range(2):
        creating = False
        try:
            with transaction.atomic():
                irp = Irp.objects.select_for_update().filter(n_irp=n_irp).first()
                creating = irp is None
                if creating:
                    irp = Irp()
                    previous = {}
                else:
                    tracked_fields = set(values) | {
                        "employee_one",
                        "employee_it",
                        "theme",
                        "input_file",
                        "status",
                    }
                    previous = {
                        field: getattr(irp, field) for field in tracked_fields
                    }
                for key, value in values.items():
                    setattr(irp, key, value)
                irp.employee_one = employee_one
                irp.employee_it = employee_it
                irp.theme = theme
                irp.input_file = input_file
                irp.synchronize_imported_status()
                irp.full_clean()
                irp.save(force_insert=creating)
                if creating:
                    IrpHistory.objects.create(
                        irp=irp,
                        field_name="__imported__",
                        new_value=source_label,
                    )
                else:
                    IrpHistory.objects.create(
                        irp=irp,
                        field_name="__reimported__",
                        new_value=source_label,
                    )
                    for field, old_value in previous.items():
                        new_value = getattr(irp, field)
                        if old_value != new_value:
                            IrpHistory.objects.create(
                                irp=irp,
                                field_name=field,
                                old_value=_history_value(old_value),
                                new_value=_history_value(new_value),
                            )
                return irp
        except IntegrityError:
            if not creating or not Irp.objects.filter(n_irp=n_irp).exists():
                raise
    raise RuntimeError("Не удалось сериализовать импорт обращения")


def _history_value(value):
    if value is None:
        return "—"
    if hasattr(value, "_meta") and hasattr(value, "pk"):
        return f"{value._meta.label}:{value.pk}"
    return str(value)


def _normalize_irp_fields(d: dict) -> dict:
    """Приводит строковые значения форм к типам, ожидаемым моделью Irp."""

    out = dict(d)
    ints = (        "irp_type",
        "way",
        "how",
        "otv_t",
        "otv_kon",
        "line_one",
        "line_it",
        "result",
        "pr_out",
        "z_smo",
        "z_doctype",
        "in_smo",
        "in_doctype",
    )
    dates = ("date_create", "date_close", "data_plan", "z_dr", "in_dr", "date_cross")
    times = ("time_create", "time_cross")
    from contextlib import suppress

    for f in ints:
        v = out.get(f)
        if v in (None, ""):
            out[f] = (
                None
                if f not in ("irp_type", "way", "how", "otv_t", "otv_kon")
                else v
            )
            continue
        if isinstance(v, str):
            with suppress(ValueError):
                out[f] = int(v)
    for f in dates:
        v = out.get(f)
        parsed = flc.parse_date(v)
        out[f] = parsed
    for f in times:
        v = out.get(f)
        if isinstance(v, str):
            out[f] = _parse_time(v)
    return out


def _parse_time(value):
    import datetime

    try:
        return datetime.datetime.strptime(str(value), "%H:%M").time()
    except ValueError:
        return None


class ExcelIrpFile:
    """Импорт обращений из Excel-файла (структура адаптируется под заказчика).

    Первая строка — заголовки (русские подписи), каждая последующая — запись
    обращения. Формат идентичен XML (G1*), протокол обработки — FLCP.
    """

    kind = "excel"
    mask = "*.xlsx"

    #: соответствие «Заголовок колонки» -> поле модели
    COLUMNS = {
        "УНр": "n_irp",
        "Вид обращения": "irp_type",
        "Дата поступления": "date_create",
        "Время поступления": "time_create",
        "Источник": "way",
        "Организация-источник": "way_n",
        "Способ": "how",
        "Тема": "theme",
        "Комментарий к теме": "theme_comment",
        "Содержание": "text",
        "Сведения о жалобе": "zh_d",
        "Тип ответств. организации": "otv_t",
        "Ответств. организация": "otv_kon",
        "Принял (GUID)": "employee_1",
        "Линия принятия": "line_one",
        "Ответственный (GUID)": "employee_it",
        "Линия рассмотрения": "line_it",
        "Плановая дата": "data_plan",
        "Дата закрытия": "date_close",
        "Результат": "result",
        "Фамилия": "z_f",
        "Имя": "z_i",
        "Отчество": "z_o",
        "Дата рождения": "z_dr",
        "ЕНП": "z_enp",
        "Страховая": "z_smo",
        "Документ": "z_doctype",
        "Серия документа": "z_docser",
        "Номер документа": "z_docnum",
        "Адрес": "adr",
        "Телефон": "phone",
        "E-mail": "e_mail",
        "Фамилия (застрах.)": "in_f",
        "Имя (застрах.)": "in_i",
        "Отчество (застрах.)": "in_o",
        "Дата рождения (застрах.)": "in_dr",
        "ЕНП (застрах.)": "in_enp",
        "Страховая (застрах.)": "in_smo",
        "Документ (застрах.)": "in_doctype",
        "Серия (застрах.)": "in_docser",
        "Номер (застрах.)": "in_docnum",
        "Переадресация": "pr_out",
        "Дата направления": "date_cross",
        "Время направления": "time_cross",
    }

    def __init__(self, org, filepath, in_dir=None, out_dir=None, archive_dir=None):
        self.org = int(org)
        self.real_file = Path(filepath)
        self.basename = self.real_file.name
        self.errors = []
        self.rows = 0
        self.archived_path: Path | None = None
        self._out_dir = Path(out_dir or settings.EXCHANGE_OUT)
        self._archive_dir = Path(archive_dir or settings.EXCHANGE_ARCHIVE)

    def process(self) -> ImportResult:
        from openpyxl import load_workbook

        wb = None
        try:
            validate_regular_exchange_input(self.real_file)
            if self.real_file.stat().st_size > MAX_EXCHANGE_FILE_SIZE:
                raise ValueError("Размер файла превышает 20 МБ")
            validate_xlsx_container(self.real_file)
            with transaction.atomic():
                wb = load_workbook(self.real_file, read_only=True, data_only=True)
                ws = wb.active
                rows = ws.iter_rows(values_only=True)
                try:
                    header = list(next(rows))
                except StopIteration:
                    header = []
                mapping = self._map_header(header)
                for r in rows:
                    if all(v in (None, "") for v in r):
                        continue
                    raw = {
                        field: r[idx] if idx < len(r) else None
                        for field, idx in mapping.items()
                    }
                    rec = _excel_row_to_irp(raw)
                    self._import_one(rec)
                if self.errors:
                    transaction.set_rollback(True)
        except ValueError as exc:
            self.errors.append(flc.error_result("EXCEL", str(exc)))
        except Exception:  # noqa: BLE001 -- log details, expose stable FLCP error
            logger.exception(
                "Unexpected Excel import failure for %s (org=%s)",
                self.basename,
                self.org,
            )
            self.errors.append(flc.error_result("EXCEL", SAFE_INTERNAL_IMPORT_ERROR))
        finally:
            if wb is not None:
                wb.close()
        if self.errors:
            self.rows = 0
        self.archived_path = self._archive()
        return ImportResult(
            filename=self.basename,
            org=self.org,
            kind=self.kind,
            errors=list(self.errors),
            rows=self.rows,
            validated=not self.errors,
        )

    def _map_header(self, header) -> dict:
        mapping = {}
        unknown = []
        for idx, title in enumerate(header or []):
            if title is None:
                continue
            key = str(title).strip()
            field = self.COLUMNS.get(key)
            if field:
                mapping[field] = idx
            elif key:
                unknown.append(key)
        if unknown:
            self.errors.append(
                flc.error_result("EXCEL", f"Неизвестные колонки: {', '.join(unknown)}")
            )
        return mapping

    def _import_one(self, rec: dict):
        import uuid

        raw_n_irp = rec.get("n_irp")
        n_irp = (
            uuid.uuid4()
            if raw_n_irp is None
            or (isinstance(raw_n_irp, str) and not raw_n_irp.strip())
            else raw_n_irp
        )
        rec["n_irp"] = n_irp
        employee_one = Employee.objects.filter(guid=rec.get("employee_1")).first()
        if not employee_one:
            self.errors.append(
                flc.error_result("EMPLOYEE_1", "Неизвестный сотрудник", n_irp)
            )
            return
        if employee_one.org != self.org:
            self.errors.append(
                flc.error_result(
                    "EMPLOYEE_1",
                    "Сотрудник не относится к организации-отправителю",
                    n_irp,
                )
            )
            return
        employee_it = None
        e_it = rec.get("employee_it")
        if e_it:
            employee_it = Employee.objects.filter(guid=e_it).first()
            if not employee_it:
                self.errors.append(
                    flc.error_result("EMPLOYEE_IT", "Неизвестный сотрудник", n_irp)
                )
                return
        theme_txt = rec.get("theme")
        theme = (
            IrpTheme.objects.filter(code_name=str(theme_txt), version=3).first()
            if theme_txt
            else None
        )
        flc_errors = flc.validate_irp_record(rec)
        if flc_errors:
            self.errors.extend(flc_errors)
            return
        del rec["employee_1"]
        rec.pop("employee_it", None)
        rec = {k: v for k, v in rec.items() if k != "theme"}
        try:
            _upsert_imported_irp(
                values=rec,
                employee_one=employee_one,
                employee_it=employee_it,
                theme=theme,
                input_file=None,
                source_label=str(self.real_file),
            )
        except ValidationError as e:
            for key, msgs in e.message_dict.items():
                self.errors.append(flc.error_result(str(key).upper(), str(msgs), n_irp))
            return
        self.rows += 1

    def _archive(self):
        return archive_artifact(self.real_file, self._archive_dir, self.org)

    def write_flcp(self, result: ImportResult) -> Path:
        org_dir = self._out_dir / str(self.org)
        return write_unique_artifact(
            org_dir / self.basename,
            (result.flcp_bytes(),),
        )


def _excel_row_to_irp(raw: dict) -> dict:
    """Экселевская строка -> словарь модели c типами (через normalize)."""
    return _normalize_irp_fields(raw)


def discover_files(in_dir, org, masks) -> list[Path]:
    """Все файлы каталога <in>/<org>, подходящие под маски (по алфавиту)."""
    org_dir = Path(in_dir) / str(org)
    files = []
    for mask in masks:
        files.extend(
            Path(p)
            for p in glob.glob(str(org_dir / mask))
            if os.path.isfile(p) or os.path.islink(p)
        )
    return sorted(set(files), key=lambda p: p.name)


def import_all(orgs=None):
    """Обработка всех файлов exchange/in/<org> (для командной строки/Cron).

    Возвращает список ImportResult.
    """
    from apps.employee.models import ORGS

    results = []
    for org, _ in ORGS if orgs is None else ((o, "") for o in orgs):
        files = discover_files(settings.EXCHANGE_IN, org, ["users*.xml", "G1*.xml", "*.xlsx"])
        for path in files:
            name = path.name.lower()
            if name.startswith("users"):
                importer = EmployeeXMLFile(org, path)
            elif name.startswith("g1"):
                importer = IrpXMLFile(org, path)
            else:
                importer = ExcelIrpFile(org, path)
            with ArtifactRollback() as artifacts, transaction.atomic():
                result = importer.process()
                artifacts.restore_on_failure(importer.archived_path, path)
                protocol_path = importer.write_flcp(result)
                artifacts.track(protocol_path)
                status = (
                    ImportLog.Status.ERROR
                    if not result.ok
                    else ImportLog.Status.OK
                )
                import_log = ImportLog.objects.create(
                    org=result.org,
                    kind=result.kind,
                    filename=result.filename,
                    status=status,
                    rows=result.rows,
                    flcp=result.flcp_bytes().decode(
                        "windows-1251", errors="replace"
                    ),
                )
                log_event(
                    module="exchange",
                    event_type=EventLog.EventType.CREATE,
                    target=f"import:{import_log.pk}:{import_log.filename}:auto",
                )
            results.append(result)
    return results

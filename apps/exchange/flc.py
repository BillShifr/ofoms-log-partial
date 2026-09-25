"""Протокол обработки файлов обмена (FLCP) и единый форматно-логический
контроль (ФЛК) для всех способов регистрации (ТЗ «Регистрация обращений»).

Протокол — XML FLCP в кодировке windows-1251 (v1): корень FLCP с атрибутами
FNAME/FNAME_I, записи PR; код `0` — успех, `41` — ошибка.
"""

import datetime

from lxml import etree

from apps.journal.models import Irp, IrpTheme
from apps.journal.validation import validate_irp_business_rules

# код ошибки в протоколе флк
FLCP_OK = "0"
FLCP_ERROR = "41"


def ok_result(filename: str, rows: int) -> dict:
    """Запись PR «Обработано успешно»."""
    return {
        "OSHIB": FLCP_OK,
        "COMMENT": f"Ошибок нет, обработано записей: {rows}.",
    }


def error_result(field: str, comment: str, n_zap: str | int | None = None) -> dict:
    """Запись PR об ошибке (поле IM_POL/BAS_EL/N_ZAP по образцу v1)."""
    res = {"OSHIB": FLCP_ERROR, "IM_POL": str(field).upper(), "COMMENT": str(comment)}
    if n_zap is not None:
        res["N_ZAP"] = str(n_zap)
    return res


def build_flcp(filename: str, errors: list[dict]) -> bytes:
    """Формирует XML-протокол FLCP (windows-1251) по списку записей PR."""
    root = etree.Element("FLCP", FNAME=filename, FNAME_I=filename)
    for e in errors:
        root.append(etree.Element("PR", {str(k): str(v) for k, v in e.items()}))
    return etree.tostring(
        root, pretty_print=True, encoding="windows-1251", xml_declaration=True
    )


def _check_record(
    d: dict,
    *,
    is_irp: bool = True,
    n_key: str = "n_irp",
) -> list[dict]:
    """Единый ФЛК записи (перед сохранением). Возвращает список ошибок PR.

    Проверяются обязательные поля, значения справочников, наличие темы
    (актуальная версия) и сотрудников по GUID (v1: load_emploees.py).
    """
    errors: list[dict] = []
    raw = d.get(n_key)
    n_zap = str(raw) if raw is not None else None

    def err(field, comment):
        errors.append(error_result(field, comment, n_zap))

    def missing(field):
        value = d.get(field)
        return not value or (isinstance(value, str) and not value.strip())

    if is_irp:
        for f in (
            "n_irp",
            "irp_type",
            "date_create",
            "way",
            "how",
            "theme",
            "otv_t",
            "otv_kon",
            "data_plan",
            "employee_1",
        ):
            if missing(f):
                err(f, "Обязательное поле не заполнено")
        for field_name in (
            "irp_type",
            "way",
            "how",
            "otv_t",
            "otv_kon",
            "line_one",
            "line_it",
            "result",
            "zh_d",
            "pr_out",
            "z_smo",
            "z_doctype",
            "in_smo",
            "in_doctype",
        ):
            value = d.get(field_name)
            if value in (None, ""):
                continue
            allowed = {choice for choice, _ in Irp._meta.get_field(field_name).choices}
            if value not in allowed:
                err(field_name, "Значение вне справочника")
        theme_txt = d.get("theme")
        if theme_txt:
            theme_exists = IrpTheme.objects.filter(
                code_name=str(theme_txt), version=3
            ).exists()
            if not theme_exists:
                err("theme", f"Тема обращения {theme_txt} не из справочника")
        for issue in validate_irp_business_rules(d):
            err(issue.field, issue.message)
    return errors


def validate_irp_record(d: dict) -> list[dict]:
    """ФЛК записи обращения (общий для XML и Excel)."""
    return _check_record(d, is_irp=True)


def validate_users_record(d: dict) -> list[dict]:
    """ФЛК записи сотрудника (users*.xml)."""
    errors: list[dict] = []
    fullname = d.get("USER_FULLNAME")
    guid = d.get("USER_UUID")
    if not fullname:
        errors.append(error_result("USER_FULLNAME", "Обязательное поле не заполнено"))
    if not guid:
        errors.append(error_result("USER_UUID", "Обязательное поле не заполнено"))
    return errors


def parse_date(value):
    """Безопасный разбор даты из строки (ISO или ДД.ММ.ГГГГ)."""
    if not value:
        return None
    if isinstance(value, datetime.date):
        return value
    text = str(value).strip()
    for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%d.%m.%y"):
        try:
            return datetime.datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None

"""Протокол обработки файлов обмена (FLCP) и единый форматно-логический
контроль (ФЛК) для всех способов регистрации (ТЗ «Регистрация обращений»).

Протокол — XML FLCP в кодировке windows-1251 (v1): корень FLCP с атрибутами
FNAME/FNAME_I, записи PR; код `0` — успех, `41` — ошибка.
"""

import datetime

from lxml import etree

from apps.employee.models import ORGS
from apps.journal.models import (
    IRP_HOW,
    IRP_TYPES,
    IRP_WAYS,
    LINES,
    OTV_T,
    RESULTS,
    ZH_TYPES,
    IrpTheme,
)

# Код ошибки в протоколе ФЛК
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
            if not d.get(f):
                err(f, "Обязательное поле не заполнено")
        if d.get("irp_type") not in [c for c, _ in IRP_TYPES]:
            err("irp_type", "Вид обращения вне справочника")
        if d.get("way") not in [c for c, _ in IRP_WAYS]:
            err("way", "Источник поступления вне справочника")
        if d.get("how") not in [c for c, _ in IRP_HOW]:
            err("how", "Способ обращения вне справочника")
        if d.get("otv_t") not in [c for c, _ in OTV_T]:
            err("otv_t", "Тип ответственной организации вне справочника")
        if d.get("otv_kon") not in [c for c, _ in ORGS]:
            err("otv_kon", "Организация вне реестра (код ОКАТО/реестра ОМС)")
        if d.get("line_one") not in [None, ""] and d.get("line_one") not in [
            c for c, _ in LINES
        ]:
            err("line_one", "Линия вне справочника")
        if d.get("line_it") not in [None, ""] and d.get("line_it") not in [
            c for c, _ in LINES
        ]:
            err("line_it", "Линия вне справочника")
        if d.get("result") not in [None, ""] and d.get("result") not in [
            c for c, _ in RESULTS
        ]:
            err("result", "Исход обработки вне справочника")
        if d.get("zh_d") not in [None, ""] and d.get("zh_d") not in [
            c for c, _ in ZH_TYPES
        ]:
            err("zh_d", "Сведения о жалобе вне справочника")
        theme_txt = d.get("theme")
        if theme_txt:
            theme_exists = IrpTheme.objects.filter(
                code_name=str(theme_txt), version=3
            ).exists()
            if not theme_exists:
                err("theme", f"Тема обращения {theme_txt} не из справочника")
        if d.get("way") == 5 and not d.get("way_n"):
            err("way_n", "Укажите организацию-источник при способе 5")
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

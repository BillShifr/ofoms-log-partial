"""Исходящий пакет обращений по внутреннему версионированному контракту.

Контракт воспроизводит фактически поддерживаемую структуру G1 текущей системы,
но не является официальным Приложением №10 к ТЗ.
"""

from datetime import datetime

from lxml import etree

CONTRACT_ID = "tfoms-journal-current"
CONTRACT_VERSION = "1.0"
CONTRACT_MARKER = f"{CONTRACT_ID}/{CONTRACT_VERSION}"
CONTRACT_FILENAME = "journal-outbound-v1.xsd"

ROOT_FIELDS = (
    "n_irp",
    "irp_type",
    "date_create",
    "time_create",
    "way",
    "way_n",
    "how",
    "theme",
    "theme_comment",
    "text",
    "zh_d",
    "otv_t",
    "otv_kon",
    "employee_one",
    "line_one",
    "employee_it",
    "line_it",
    "data_plan",
    "date_close",
    "result",
)
Z_FIELDS = (
    "z_f",
    "z_i",
    "z_o",
    "z_dr",
    "z_enp",
    "z_smo",
    "z_doctype",
    "z_docser",
    "z_docnum",
    "adr",
    "phone",
    "e_mail",
)
IN_FIELDS = (
    "in_f",
    "in_i",
    "in_o",
    "in_dr",
    "in_enp",
    "in_smo",
    "in_doctype",
    "in_docser",
    "in_docnum",
)
REDIRECT_FIELDS = ("pr_out", "date_cross", "time_cross")


def _value(irp, field: str):
    if field == "theme":
        return irp.theme.code_name
    if field in ("employee_one", "employee_it"):
        employee = getattr(irp, field)
        return employee.guid if employee else None
    return getattr(irp, field)


def _text(value) -> str:
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _append(parent, field: str, value, *, required: bool = False) -> None:
    if value in (None, "") and not required:
        return
    node = etree.SubElement(parent, field)
    node.text = "" if value is None else _text(value)


def build_outbound_package(queryset, *, org: int, generated_at: datetime) -> bytes:
    """Сериализует queryset в детерминированную структуру текущего G1."""
    root = etree.Element("IRP_LIST")
    header = etree.SubElement(root, "ZGLV")
    filename = f"G1OUT_{org}_{generated_at:%Y%m%d%H%M%S}.xml"
    for field, value in (
        ("filename", filename),
        ("version", CONTRACT_MARKER),
        ("data", generated_at.date()),
        ("year", f"{generated_at.year:04d}"),
        ("month", f"{generated_at.month:02d}"),
        ("day", f"{generated_at.day:02d}"),
        ("time", generated_at.time().replace(microsecond=0)),
        ("smo", org),
    ):
        _append(header, field, value, required=True)

    required = {
        "n_irp",
        "irp_type",
        "date_create",
        "way",
        "how",
        "theme",
        "otv_t",
        "otv_kon",
        "employee_one",
        "data_plan",
    }
    for irp in queryset.iterator(chunk_size=500):
        node = etree.SubElement(root, "IRP")
        for field in ROOT_FIELDS:
            _append(node, field, _value(irp, field), required=field in required)
        if any(_value(irp, field) not in (None, "") for field in Z_FIELDS):
            block = etree.SubElement(node, "z_sv")
            for field in Z_FIELDS:
                _append(block, field, _value(irp, field))
        if any(_value(irp, field) not in (None, "") for field in IN_FIELDS):
            block = etree.SubElement(node, "in_sv")
            for field in IN_FIELDS:
                _append(block, field, _value(irp, field))
        for field in REDIRECT_FIELDS:
            _append(node, field, _value(irp, field))
    return etree.tostring(
        root,
        pretty_print=True,
        encoding="windows-1251",
        xml_declaration=True,
    )

"""Расчёт отчётных форм (ТЗ разд. 2.5, Приложения №1–9).

Макеты отчётных форм в ТЗ не приведены — структура отчётов спроектирована
на основе реквизитов регистрационно-контрольной карты (Irp) и требований
письма ФФОМС к аналитике (п. 37–39).
"""

import datetime
from collections.abc import Callable
from dataclasses import dataclass

from django.db.models import Q

from apps.employee.models import ORGS, TFOMS
from apps.journal.models import (
    IRP_HOW,
    IRP_TYPES,
    IRP_WAYS,
    LINES,
    RESULTS,
    Irp,
    IrpTheme,
)


@dataclass
class ReportFilters:
    """Общие фильтры отчётов (ТЗ: период, способ, исполнитель, источник, закрытые)."""

    date_from: datetime.date | None = None
    date_to: datetime.date | None = None
    how: int | None = None
    way: int | None = None
    otv_kon: int | None = None
    only_closed: bool = False

    def apply(self, qs):
        if self.date_from:
            qs = qs.filter(date_create__gte=self.date_from)
        if self.date_to:
            qs = qs.filter(date_create__lte=self.date_to)
        if self.how is not None:
            qs = qs.filter(how=self.how)
        if self.way is not None:
            qs = qs.filter(way=self.way)
        if self.otv_kon is not None:
            qs = qs.filter(otv_kon=self.otv_kon)
        if self.only_closed:
            qs = qs.filter(date_close__isnull=False)
        return qs

    def scoped(self, qs, org: int):
        if org != TFOMS:
            qs = qs.filter(otv_kon=org)
        return qs


@dataclass
class Report:
    slug: str
    number: int
    title: str
    description: str
    columns: list[tuple[str, str]]
    build: Callable[[int, ReportFilters], list[dict]]

    @property
    def labels(self) -> list[str]:
        return [label for _, label in self.columns]

    @property
    def keys(self) -> list[str]:
        return [key for key, _ in self.columns]


# ---------------------------------------------------------------------------
# Вспомогательные преобразователи справочников
# ---------------------------------------------------------------------------

def _label(choices, value):
    if value is None:
        return "—"
    for code, name in choices:
        if code == value:
            return name
    return str(value)


def _irp_type_label(value):
    return _label(IRP_TYPES, value)


def _how_label(value):
    return _label(IRP_HOW, value)


def _way_label(value):
    return _label(IRP_WAYS, value)


def _result_label(value):
    return _label(RESULTS, value)


def _line_label(value):
    return _label(LINES, value)


def _org_label(value):
    return _label(ORGS, value)


def _theme_label(theme):
    return f"{theme.code_name} — {theme.title}" if theme else "—"


def _monthly(filters: ReportFilters) -> bool:
    if filters.date_from and filters.date_to:
        return (filters.date_to - filters.date_from).days > 31
    return True


def _bucket(date: datetime.date, monthly: bool) -> datetime.date:
    if monthly:
        return datetime.date(date.year, date.month, 1)
    return date


def _bucket_label(date: datetime.date, monthly: bool) -> str:
    return date.strftime("%m.%Y" if monthly else "%d.%m.%Y")


def _percent(part: float, whole: int) -> str:
    if not whole:
        return "0,0"
    return f"{part / whole * 100:.1f}".replace(".", ",")


def _avg_days(rows: list[dict]) -> str:
    days = [
        (r["date_close"] - r["date_create"]).days
        for r in rows
        if r.get("date_close") and r.get("date_create")
    ]
    if not days:
        return "—"
    return f"{sum(days) / len(days):.1f}".replace(".", ",")


def _base(user_org: int, filters: ReportFilters):
    return filters.scoped(filters.apply(Irp.objects.all()), user_org)


# ---------------------------------------------------------------------------
# Прил. №1 — Количество поступивших обращений
# ---------------------------------------------------------------------------

def r1_by_volume(user_org: int, filters: ReportFilters):
    monthly = _monthly(filters)
    data = list(_base(user_org, filters).values("date_create", "irp_type", "date_close"))
    buckets: dict[datetime.date, dict] = {}
    for row in data:
        key = _bucket(row["date_create"], monthly)
        bucket = buckets.setdefault(key, {})
        bucket["total"] = bucket.get("total", 0) + 1
        bucket[f"t{row['irp_type']}"] = bucket.get(f"t{row['irp_type']}", 0) + 1
        if row["date_close"]:
            bucket["closed"] = bucket.get("closed", 0) + 1
    rows = [
        {"period": _bucket_label(key, monthly), **buckets[key]}
        for key in sorted(buckets)
    ]
    total = {
        "period": "ИТОГО",
        "total": sum(r.get("total", 0) for r in rows),
        "closed": sum(r.get("closed", 0) for r in rows),
    }
    for t in range(1, 6):
        total[f"t{t}"] = sum(r.get(f"t{t}", 0) for r in rows)
    rows.append(total)
    return rows


# ---------------------------------------------------------------------------
# Прил. №2 — Обращения ЗЛ по виду обращения
# ---------------------------------------------------------------------------

def r2_by_type(user_org: int, filters: ReportFilters):
    data = list(
        _base(user_org, filters).values("irp_type", "date_create", "date_close")
    )
    by_type: dict[int, list] = {}
    for row in data:
        by_type.setdefault(row["irp_type"], []).append(row)
    rows = []
    for irp_type, items in sorted(by_type.items()):
        rows.append(
            {
                "type": _irp_type_label(irp_type),
                "total": len(items),
                "percent": _percent(len(items), len(data)),
                "closed": sum(1 for r in items if r["date_close"]),
                "avg_days": _avg_days(items),
            }
        )
    rows.append(
        {
            "type": "ИТОГО",
            "total": len(data),
            "percent": "100,0",
            "closed": sum(1 for r in data if r["date_close"]),
            "avg_days": _avg_days(data),
        }
    )
    return rows


# ---------------------------------------------------------------------------
# Прил. №3 — Досудебная и судебная защита прав ЗЛ по причинам обращений
# ---------------------------------------------------------------------------

def r3_protection(user_org: int, filters: ReportFilters):
    qs = _base(user_org, filters).filter(Q(irp_type=2) | Q(zh_d__isnull=False))
    data = list(qs.select_related("theme").values("theme", "zh_d"))
    themes = {}
    for row in data:
        theme_id = row["theme"]
        item = themes.setdefault(theme_id, {"theme": theme_id, "well": 0, "pre": 0, "court": 0, "bad": 0, "total": 0})
        item["total"] += 1
        zh = row["zh_d"]
        if zh and (zh.startswith("1") or zh == "1"):
            item["well"] += 1
            if zh == "1.1":
                item["pre"] += 1
            if zh == "1.2":
                item["court"] += 1
        elif zh == "2":
            item["bad"] += 1
    theme_names = {
        t.id: _theme_label(t)
        for t in IrpTheme.objects.filter(id__in=themes).only("code_name", "title")
    }
    rows = []
    for item in themes.values():
        item["theme"] = theme_names.get(item["theme"], "—")
        rows.append(item)
    rows.sort(key=lambda r: (-r["total"], r["theme"]))
    rows.append(
        {
            "theme": "ИТОГО",
            "well": sum(r["well"] for r in rows),
            "pre": sum(r["pre"] for r in rows),
            "court": sum(r["court"] for r in rows),
            "bad": sum(r["bad"] for r in rows),
            "total": sum(r["total"] for r in rows),
        }
    )
    return rows


# ---------------------------------------------------------------------------
# Прил. №4 — Жалобы и причины
# ---------------------------------------------------------------------------

def r4_complaints(user_org: int, filters: ReportFilters):
    data = list(
        _base(user_org, filters)
        .filter(irp_type=2)
        .select_related("theme")
        .values("theme", "date_close")
    )
    themes = {}
    for row in data:
        item = themes.setdefault(row["theme"], {"theme": row["theme"], "total": 0, "closed": 0})
        item["total"] += 1
        if row["date_close"]:
            item["closed"] += 1
    theme_names = {
        t.id: _theme_label(t)
        for t in IrpTheme.objects.filter(id__in=themes).only("code_name", "title")
    }
    total_all = sum(r["total"] for r in themes.values())
    rows = []
    for item in themes.values():
        rows.append(
            {
                "theme": theme_names.get(item["theme"], "—"),
                "total": item["total"],
                "closed": item["closed"],
                "percent": _percent(item["total"], total_all),
            }
        )
    rows.sort(key=lambda r: (-r["total"], r["theme"]))
    rows.append(
        {
            "theme": "ИТОГО",
            "total": total_all,
            "closed": sum(r["closed"] for r in rows),
            "percent": "100,0",
        }
    )
    return rows


# ---------------------------------------------------------------------------
# Прил. №5 — Заявления
# ---------------------------------------------------------------------------

def r5_applications(user_org: int, filters: ReportFilters):
    monthly = _monthly(filters)
    data = list(
        _base(user_org, filters)
        .filter(irp_type=4)
        .values("date_create", "date_close", "result")
    )
    buckets: dict[datetime.date, dict] = {}
    for row in data:
        key = _bucket(row["date_create"], monthly)
        bucket = buckets.setdefault(key, {})
        bucket["month"] = _bucket_label(key, monthly)
        bucket["total"] = bucket.get("total", 0) + 1
        bucket["satisfied"] = bucket.get("satisfied", 0) + (1 if row["result"] == 3 else 0)
        bucket["rejected"] = bucket.get("rejected", 0) + (1 if row["result"] == 4 else 0)
        bucket["pending"] = bucket.get("pending", 0) + (1 if not row["date_close"] else 0)
    rows = [buckets[key] for key in sorted(buckets)]
    rows.append(
        {
            "month": "ИТОГО",
            "total": sum(r["total"] for r in rows),
            "satisfied": sum(r["satisfied"] for r in rows),
            "rejected": sum(r["rejected"] for r in rows),
            "pending": sum(r["pending"] for r in rows),
        }
    )
    return rows


# ---------------------------------------------------------------------------
# Прил. №6 — Обращение за разъяснением
# ---------------------------------------------------------------------------

def r6_clarification(user_org: int, filters: ReportFilters):
    data = list(
        _base(user_org, filters)
        .filter(irp_type=1)
        .select_related("theme")
        .values("theme", "how", "result", "date_close")
    )
    themes = {}
    for row in data:
        item = themes.setdefault(
            row["theme"], {"theme": row["theme"], "total": 0, "hotline": 0, "consulted": 0, "closed": 0}
        )
        item["total"] += 1
        item["hotline"] += 1 if row["how"] == 1 else 0
        item["consulted"] += 1 if row["result"] == 1 else 0
        item["closed"] += 1 if row["date_close"] else 0
    theme_names = {
        t.id: _theme_label(t)
        for t in IrpTheme.objects.filter(id__in=themes).only("code_name", "title")
    }
    rows = []
    for item in themes.values():
        item["theme"] = theme_names.get(item["theme"], "—")
        rows.append(item)
    rows.sort(key=lambda r: (-r["total"], r["theme"]))
    rows.append(
        {
            "theme": "ИТОГО",
            "total": sum(r["total"] for r in rows),
            "hotline": sum(r["hotline"] for r in rows),
            "consulted": sum(r["consulted"] for r in rows),
            "closed": sum(r["closed"] for r in rows),
        }
    )
    return rows


# ---------------------------------------------------------------------------
# Прил. №7 и №8 — Горячая линия (жалобы / консультации)
# ---------------------------------------------------------------------------

def _hotline(irp_type: int, user_org: int, filters: ReportFilters):
    monthly = _monthly(filters)
    data = list(
        _base(user_org, filters)
        .filter(how=1, irp_type=irp_type)
        .values("date_create", "line_one", "pr_out", "date_close")
    )
    buckets: dict[datetime.date, dict] = {}
    for row in data:
        key = _bucket(row["date_create"], monthly)
        bucket = buckets.setdefault(key, {})
        bucket["month"] = _bucket_label(key, monthly)
        bucket["total"] = bucket.get("total", 0) + 1
        bucket["op1"] = bucket.get("op1", 0) + (1 if row["line_one"] == 1 else 0)
        bucket["op2"] = bucket.get("op2", 0) + (1 if row["line_one"] == 2 else 0)
        bucket["sp1"] = bucket.get("sp1", 0) + (1 if row["line_one"] == 3 else 0)
        bucket["redirected"] = bucket.get("redirected", 0) + (1 if row["pr_out"] else 0)
        bucket["closed"] = bucket.get("closed", 0) + (1 if row["date_close"] else 0)
    rows = [buckets[key] for key in sorted(buckets)]
    rows.append(
        {
            "month": "ИТОГО",
            "total": sum(r["total"] for r in rows),
            "op1": sum(r["op1"] for r in rows),
            "op2": sum(r["op2"] for r in rows),
            "sp1": sum(r["sp1"] for r in rows),
            "redirected": sum(r["redirected"] for r in rows),
            "closed": sum(r["closed"] for r in rows),
        }
    )
    return rows


def r7_hotline_complaints(user_org: int, filters: ReportFilters):
    return _hotline(2, user_org, filters)


def r8_hotline_consultations(user_org: int, filters: ReportFilters):
    return _hotline(1, user_org, filters)


# ---------------------------------------------------------------------------
# Прил. №9 — Обращения граждан (персональный список)
# ---------------------------------------------------------------------------

def r9_personal(user_org: int, filters: ReportFilters):
    qs = _base(user_org, filters).select_related("theme", "employee_it")
    return [
        {
            "n_irp": row.n_irp,
            "date": row.date_create.strftime("%d.%m.%Y"),
            "fio": " ".join(x for x in (row.z_f, row.z_i, row.z_o) if x),
            "birth": row.z_dr.strftime("%d.%m.%Y") if row.z_dr else "—",
            "enp": row.z_enp or "—",
            "smo": _org_label(row.z_smo),
            "phone": row.phone or "—",
            "type": _irp_type_label(row.irp_type),
            "theme": _theme_label(row.theme),
            "text": (row.text or "—")[:200],
            "how": _how_label(row.how),
            "way": _way_label(row.way),
            "otv": _org_label(row.otv_kon),
            "plan": row.data_plan.strftime("%d.%m.%Y"),
            "status": "закрыто" if row.date_close else "в работе",
            "result": _result_label(row.result),
        }
        for row in qs.order_by("date_create", "n_irp")
    ]


# ---------------------------------------------------------------------------
# Реестр отчётов
# ---------------------------------------------------------------------------

REPORTS: list[Report] = [
    Report(
        slug="r1_volume",
        number=1,
        title="Количество поступивших обращений",
        description="Динамика поступления обращений за период: всего, по видам, закрыто.",
        columns=[
            ("period", "Период"),
            ("total", "Всего"),
            ("t1", "Консультации"),
            ("t2", "Жалобы"),
            ("t3", "Предложения"),
            ("t4", "Заявления"),
            ("t5", "Не по сфере ОМС"),
            ("closed", "Закрыто"),
        ],
        build=r1_by_volume,
    ),
    Report(
        slug="r2_type",
        number=2,
        title="Обращения застрахованных лиц по виду обращения",
        description="Распределение обращений по видам с долей, закрытыми и средним сроком.",
        columns=[
            ("type", "Вид обращения"),
            ("total", "Всего"),
            ("percent", "Доля, %"),
            ("closed", "Закрыто"),
            ("avg_days", "Ср. срок, дней"),
        ],
        build=r2_by_type,
    ),
    Report(
        slug="r3_protection",
        number=3,
        title="Досудебная и судебная защита прав ЗЛ по причинам обращений",
        description="Жалобы по причинам (темам) с разбивкой по сведениям о жалобе.",
        columns=[
            ("theme", "Причина обращения"),
            ("well", "Обоснованные"),
            ("pre", "Из них: досудебно"),
            ("court", "Из них: судебно"),
            ("bad", "Необоснованные"),
            ("total", "Итого"),
        ],
        build=r3_protection,
    ),
    Report(
        slug="r4_complaints",
        number=4,
        title="Жалобы и причины",
        description="Жалобы, сгруппированные по причинам (темам), с закрытыми и долями.",
        columns=[
            ("theme", "Причина"),
            ("total", "Кол-во"),
            ("closed", "Закрыто"),
            ("percent", "Доля, %"),
        ],
        build=r4_complaints,
    ),
    Report(
        slug="r5_applications",
        number=5,
        title="Заявления",
        description="Движение заявлений по периодам: подано, удовлетворено, отклонено, в работе.",
        columns=[
            ("month", "Период"),
            ("total", "Подано"),
            ("satisfied", "Удовлетворено"),
            ("rejected", "Не удовлетворено"),
            ("pending", "На рассмотрении"),
        ],
        build=r5_applications,
    ),
    Report(
        slug="r6_clarification",
        number=6,
        title="Обращение за разъяснением",
        description="Консультации по темам: всего, по горячей линии, с консультацией, закрыто.",
        columns=[
            ("theme", "Тема"),
            ("total", "Всего"),
            ("hotline", "Горячая линия"),
            ("consulted", "Дана консультация"),
            ("closed", "Закрыто"),
        ],
        build=r6_clarification,
    ),
    Report(
        slug="r7_hotline_complaints",
        number=7,
        title="Горячая линия (Жалобы)",
        description="Жалобы по телефону горячей линии: по линиям, переадресовано, закрыто.",
        columns=[
            ("month", "Период"),
            ("total", "Звонков"),
            ("op1", "ОП1"),
            ("op2", "ОП2"),
            ("sp1", "СП1"),
            ("redirected", "Переадресовано"),
            ("closed", "Закрыто"),
        ],
        build=r7_hotline_complaints,
    ),
    Report(
        slug="r8_hotline_consultations",
        number=8,
        title="Горячая линия (Обращения за консультацией)",
        description="Консультации по телефону горячей линии: по линиям, переадресовано, закрыто.",
        columns=[
            ("month", "Период"),
            ("total", "Звонков"),
            ("op1", "ОП1"),
            ("op2", "ОП2"),
            ("sp1", "СП1"),
            ("redirected", "Переадресовано"),
            ("closed", "Закрыто"),
        ],
        build=r8_hotline_consultations,
    ),
    Report(
        slug="r9_personal",
        number=9,
        title="Обращения граждан — персональный список",
        description="Список обращений с персональными данными заявителей по заданному периоду.",
        columns=[
            ("n_irp", "№ обращения"),
            ("date", "Дата"),
            ("fio", "ФИО заявителя"),
            ("birth", "Дата рождения"),
            ("enp", "ЕНП"),
            ("smo", "Страховая"),
            ("phone", "Телефон"),
            ("type", "Вид"),
            ("theme", "Тема"),
            ("text", "Содержание"),
            ("how", "Способ"),
            ("way", "Источник"),
            ("otv", "Исполнитель"),
            ("plan", "Срок"),
            ("status", "Статус"),
            ("result", "Результат"),
        ],
        build=r9_personal,
    ),
]

REPORT_INDEX = {report.slug: report for report in REPORTS}

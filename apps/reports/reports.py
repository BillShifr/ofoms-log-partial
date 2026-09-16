"""Расчёт отчётных форм (ТЗ разд. 2.5, Приложения №1–9).

Макеты отчётных форм в ТЗ не приведены — структура отчётов спроектирована
на основе реквизитов регистрационно-контрольной карты (Irp) и требований
письма ФФОМС к аналитике (п. 37–39).
"""

import datetime
from collections.abc import Callable
from dataclasses import dataclass

from django.db.models import Avg, Count, DateField, DurationField, ExpressionWrapper, F, Q
from django.db.models.functions import TruncMonth

from apps.employee.models import ORGS, TFOMS
from apps.journal.models import (
    IRP_HOW,
    IRP_TYPES,
    IRP_WAYS,
    LINES,
    RESULTS,
    Irp,
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
            qs = qs.filter(employee_one__org=org)
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


def _bucket_label(date: datetime.date, monthly: bool) -> str:
    return date.strftime("%m.%Y" if monthly else "%d.%m.%Y")


def _percent(part: float, whole: int) -> str:
    if not whole:
        return "0,0"
    return f"{part / whole * 100:.1f}".replace(".", ",")


def _avg_duration_label(value) -> str:
    if value is None:
        return "—"
    return f"{value.total_seconds() / 86400:.1f}".replace(".", ",")


def _period_expression(monthly: bool):
    if monthly:
        return TruncMonth("date_create", output_field=DateField())
    return F("date_create")


def _base(user_org: int, filters: ReportFilters):
    return filters.scoped(filters.apply(Irp.objects.all()), user_org)


def has_report_data(user_org: int, filters: ReportFilters) -> bool:
    """Whether the selected scope contains source records for an export."""
    return _base(user_org, filters).exists()


# ---------------------------------------------------------------------------
# Прил. №1 — Количество поступивших обращений
# ---------------------------------------------------------------------------

def r1_by_volume(user_org: int, filters: ReportFilters):
    monthly = _monthly(filters)
    grouped = _base(user_org, filters).values(
        period_value=_period_expression(monthly)
    ).annotate(
        total=Count("pk"),
        closed=Count("pk", filter=Q(date_close__isnull=False)),
        t1=Count("pk", filter=Q(irp_type=1)),
        t2=Count("pk", filter=Q(irp_type=2)),
        t3=Count("pk", filter=Q(irp_type=3)),
        t4=Count("pk", filter=Q(irp_type=4)),
        t5=Count("pk", filter=Q(irp_type=5)),
    ).order_by("period_value")
    rows = [
        {"period": _bucket_label(row.pop("period_value"), monthly), **row}
        for row in grouped
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
    duration = ExpressionWrapper(
        F("date_close") - F("date_create"), output_field=DurationField()
    )
    grouped = list(
        _base(user_org, filters).values("irp_type").annotate(
            total=Count("pk"),
            closed=Count("pk", filter=Q(date_close__isnull=False)),
            avg_duration=Avg(duration, filter=Q(date_close__isnull=False)),
        ).order_by("irp_type")
    )
    total_count = sum(row["total"] for row in grouped)
    rows = [
        {
            "type": _irp_type_label(row["irp_type"]),
            "total": row["total"],
            "percent": _percent(row["total"], total_count),
            "closed": row["closed"],
            "avg_days": _avg_duration_label(row["avg_duration"]),
        }
        for row in grouped
    ]
    rows.append(
        {
            "type": "ИТОГО",
            "total": total_count,
            "percent": "100,0",
            "closed": sum(row["closed"] for row in grouped),
            "avg_days": _avg_duration_label(
                sum(
                    (row["avg_duration"] * row["closed"] for row in grouped if row["avg_duration"]),
                    datetime.timedelta(),
                ) / sum(row["closed"] for row in grouped)
                if sum(row["closed"] for row in grouped)
                else None
            ),
        }
    )
    return rows


# ---------------------------------------------------------------------------
# Прил. №3 — Досудебная и судебная защита прав ЗЛ по причинам обращений
# ---------------------------------------------------------------------------

def r3_protection(user_org: int, filters: ReportFilters):
    grouped = _base(user_org, filters).filter(
        Q(irp_type=2) | Q(zh_d__isnull=False)
    ).values("theme__code_name", "theme__title").annotate(
        well=Count("pk", filter=Q(zh_d__startswith="1")),
        pre=Count("pk", filter=Q(zh_d="1.1")),
        court=Count("pk", filter=Q(zh_d="1.2")),
        bad=Count("pk", filter=Q(zh_d="2")),
        total=Count("pk"),
    )
    rows = [
        {
            "theme": f"{row['theme__code_name']} — {row['theme__title']}",
            "well": row["well"],
            "pre": row["pre"],
            "court": row["court"],
            "bad": row["bad"],
            "total": row["total"],
        }
        for row in grouped
    ]
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
    grouped = list(
        _base(user_org, filters).filter(irp_type=2)
        .values("theme__code_name", "theme__title")
        .annotate(
            total=Count("pk"),
            closed=Count("pk", filter=Q(date_close__isnull=False)),
        )
    )
    total_all = sum(row["total"] for row in grouped)
    rows = [
        {
            "theme": f"{row['theme__code_name']} — {row['theme__title']}",
            "total": row["total"],
            "closed": row["closed"],
            "percent": _percent(row["total"], total_all),
        }
        for row in grouped
    ]
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
    grouped = _base(user_org, filters).filter(irp_type=4).values(
        period_value=_period_expression(monthly)
    ).annotate(
        total=Count("pk"),
        satisfied=Count("pk", filter=Q(result=3)),
        rejected=Count("pk", filter=Q(result=4)),
        pending=Count("pk", filter=Q(date_close__isnull=True)),
    ).order_by("period_value")
    rows = [
        {"month": _bucket_label(row.pop("period_value"), monthly), **row}
        for row in grouped
    ]
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
    grouped = _base(user_org, filters).filter(irp_type=1).values(
        "theme__code_name", "theme__title"
    ).annotate(
        total=Count("pk"),
        hotline=Count("pk", filter=Q(how=1)),
        consulted=Count("pk", filter=Q(result=1)),
        closed=Count("pk", filter=Q(date_close__isnull=False)),
    )
    rows = [
        {
            "theme": f"{row['theme__code_name']} — {row['theme__title']}",
            "total": row["total"],
            "hotline": row["hotline"],
            "consulted": row["consulted"],
            "closed": row["closed"],
        }
        for row in grouped
    ]
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
    grouped = _base(user_org, filters).filter(how=1, irp_type=irp_type).values(
        period_value=_period_expression(monthly)
    ).annotate(
        total=Count("pk"),
        op1=Count("pk", filter=Q(line_one=1)),
        op2=Count("pk", filter=Q(line_one=2)),
        sp1=Count("pk", filter=Q(line_one=3)),
        redirected=Count("pk", filter=Q(pr_out__isnull=False)),
        closed=Count("pk", filter=Q(date_close__isnull=False)),
    ).order_by("period_value")
    rows = [
        {"month": _bucket_label(row.pop("period_value"), monthly), **row}
        for row in grouped
    ]
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

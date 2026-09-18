"""Единые доменные правила форматно-логического контроля обращений."""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from typing import Any

from django.core.exceptions import ValidationError


@dataclass(frozen=True)
class IrpValidationIssue:
    field: str
    message: str
    code: str = "invalid"


def validate_irp_business_rules(values: Mapping[str, Any]) -> list[IrpValidationIssue]:
    """Проверяет одинаковые бизнес-правила для формы, XML и Excel."""
    issues: list[IrpValidationIssue] = []

    def add(field: str, message: str, code: str = "invalid") -> None:
        issues.append(IrpValidationIssue(field, message, code))

    if values.get("irp_type") != 2 and values.get("zh_d") not in (None, ""):
        add("zh_d", "Сведения о жалобе допустимы только для жалобы.")
    if not values.get("pr_out") and (
        values.get("date_cross") or values.get("time_cross")
    ):
        add(
            "pr_out",
            "Дата и время направления допустимы только при наличии признака направления.",
        )
    if values.get("time_cross") and not values.get("date_cross"):
        add("date_cross", "Для времени направления укажите дату направления.")
    if values.get("way") == 5 and not values.get("way_n"):
        add("way_n", "Укажите организацию-источник.", "conditional_required")

    date_close = values.get("date_close")
    result = values.get("result")
    if bool(date_close) != bool(result):
        add(
            "date_close" if result else "result",
            "Для закрытия обращения одновременно укажите дату и исход.",
        )

    date_create = values.get("date_create")
    data_plan = values.get("data_plan")
    if (
        isinstance(date_create, date)
        and isinstance(data_plan, date)
        and data_plan < date_create
    ):
        add("data_plan", "Плановый срок не может быть раньше даты поступления.")
    if (
        isinstance(date_create, date)
        and isinstance(date_close, date)
        and date_close < date_create
    ):
        add("date_close", "Дата закрытия не может быть раньше даты поступления.")

    if values.get("status") == "closed" and not (date_close and result):
        add("date_close", "Для статуса «Закрыто» укажите дату и исход.")
    return issues


def raise_irp_business_validation(values: Mapping[str, Any]) -> None:
    issues = validate_irp_business_rules(values)
    if not issues:
        return
    errors: dict[str, list[ValidationError]] = {}
    for issue in issues:
        errors.setdefault(issue.field, []).append(
            ValidationError(issue.message, code=issue.code)
        )
    raise ValidationError(errors)

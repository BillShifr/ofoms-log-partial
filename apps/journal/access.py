"""Canonical operational visibility rules for citizen appeals."""

from django.db.models import Q, QuerySet

from apps.employee.models import TFOMS
from apps.journal.models import Irp


def visible_irps_for_user(user, queryset: QuerySet | None = None) -> QuerySet:
    """Appeals owned by or currently routed to the user's organization."""
    queryset = queryset if queryset is not None else Irp.objects.all()
    if user.is_superuser or user.org == TFOMS:
        return queryset
    return queryset.filter(Q(employee_one__org=user.org) | Q(otv_kon=user.org))


def user_can_access_irp(user, appeal: Irp) -> bool:
    return bool(
        user.is_superuser
        or user.org == TFOMS
        or appeal.employee_one.org == user.org
        or appeal.otv_kon == user.org
    )

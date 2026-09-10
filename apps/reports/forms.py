"""Форма общих фильтров отчётов (ТЗ разд. 2.5)."""

from django import forms

from apps.employee.models import ORGS, TFOMS
from apps.journal.models import IRP_HOW, IRP_WAYS
from apps.reports.reports import ReportFilters

_EMPTY = [("", "Все")]


class ReportFilterForm(forms.Form):
    """Период регистрации, способ, исполнитель, источник, только закрытые."""

    date_from = forms.DateField(
        required=False,
        label="Регистрация с",
        widget=forms.DateInput(attrs={"type": "date"}),
    )
    date_to = forms.DateField(
        required=False,
        label="по",
        widget=forms.DateInput(attrs={"type": "date"}),
    )
    how = forms.TypedChoiceField(
        required=False,
        label="Способ обращения",
        coerce=int,
        empty_value=None,
        choices=_EMPTY + list(IRP_HOW),
    )
    way = forms.TypedChoiceField(
        required=False,
        label="Источник получения",
        coerce=int,
        empty_value=None,
        choices=_EMPTY + list(IRP_WAYS),
    )
    otv_kon = forms.TypedChoiceField(
        required=False,
        label="Исполнитель (ТФОМС/СМО)",
        coerce=int,
        empty_value=None,
        choices=_EMPTY + list(ORGS),
    )
    only_closed = forms.BooleanField(
        required=False, label="Учитывать только закрытые обращения"
    )

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        if user is not None and user.org != TFOMS:
            self.fields["otv_kon"].choices = _EMPTY + [
                o for o in ORGS if o[0] == user.org
            ]

    def clean(self):
        cleaned = super().clean()
        start = cleaned.get("date_from")
        end = cleaned.get("date_to")
        if start and end and start > end:
            raise forms.ValidationError("Дата начала периода не может быть позже даты окончания")
        return cleaned

    def to_filters(self) -> ReportFilters:
        return ReportFilters(
            date_from=self.cleaned_data.get("date_from"),
            date_to=self.cleaned_data.get("date_to"),
            how=self.cleaned_data.get("how"),
            way=self.cleaned_data.get("way"),
            otv_kon=self.cleaned_data.get("otv_kon"),
            only_closed=bool(self.cleaned_data.get("only_closed")),
        )

    @property
    def has_filters(self) -> bool:
        return any(
            self.cleaned_data.get(field)
            for field in ("date_from", "date_to", "how", "way", "otv_kon", "only_closed")
        )

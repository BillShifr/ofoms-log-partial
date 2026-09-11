"""Формы журнала: создание/редактирование обращения и панель фильтров."""

import datetime
import uuid

from django import forms
from django.db.models import Q

from apps.employee.models import ORGS, Employee
from apps.journal.models import (
    IRP_HOW,
    IRP_TYPES,
    Irp,
    IrpAnswer,
    IrpTheme,
)


def _assignable_employees(user, current_id=None):
    """Активные исполнители в доступном org scope плюс текущее назначение."""
    scope = Q() if user.org == 81000 else Q(org__in=(user.org, 81000))
    availability = Q(is_active=True)
    if current_id:
        availability |= Q(pk=current_id)
    return Employee.objects.filter(scope & availability).order_by(
        "last_name", "first_name", "pk"
    )


class IrpForm(forms.ModelForm):
    """Карточка обращения (регистрация / редактирование)."""

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        # Темы — актуальная версия (3), как в v1
        self.fields["theme"].queryset = IrpTheme.objects.filter(version=3)
        if user is not None:
            self.fields["theme"].empty_label = "— выберите тему —"
            self.fields["otv_kon"].choices = [
                org for org in ORGS if user.org == 81000 or org[0] == user.org
            ]
            self.fields["employee_one"].disabled = True
            self.fields["employee_one"].help_text = (
                "Первичный исполнитель фиксируется при регистрации."
            )
            self.fields["employee_it"].queryset = _assignable_employees(
                user, self.instance.employee_it_id
            )
            if self.instance.pk is None:
                # По умолчанию: исполнитель = текущий пользователь,
                # организация-ответственный = организация пользователя
                self.fields["employee_one"].initial = user
                self.fields["employee_it"].initial = user
                self.fields["otv_kon"].initial = user.org
                # Уникальный номер генерируется сервером при отсутствии явного
                self.fields["n_irp"].required = False
                self.fields["n_irp"].initial = str(uuid.uuid4())
                self.fields["date_create"].initial = datetime.date.today()
                self.fields["data_plan"].initial = (
                    datetime.date.today() + datetime.timedelta(days=30)
                )

    class Meta:
        model = Irp
        fields = [
            "n_irp", "irp_type", "date_create", "time_create",
            "way", "way_n", "how", "theme", "theme_comment", "text",
            "zh_d", "otv_t", "otv_kon",
            "employee_one", "line_one", "employee_it", "line_it",
            "data_plan", "date_close", "result",
            "z_f", "z_i", "z_o", "z_dr", "z_enp", "z_smo",
            "z_doctype", "z_docser", "z_docnum",
            "adr", "phone", "e_mail",
            "in_f", "in_i", "in_o", "in_dr", "in_enp", "in_smo",
            "in_doctype", "in_docser", "in_docnum",
            "pr_out", "date_cross", "time_cross",
        ]
        widgets = {
            "theme_comment": forms.Textarea(attrs={"rows": 2}),
            "text": forms.Textarea(attrs={"rows": 3}),
            "phone": forms.TextInput(attrs={"placeholder": "+7 (___) ___-__-__"}),
            "e_mail": forms.EmailInput(attrs={"placeholder": "user@example.ru"}),
        }

    def clean_n_irp(self):
        value = self.cleaned_data.get("n_irp")
        # При регистрации без явного номера генерируем UUID (как в v1)
        if self.instance.pk is None and not value:
            value = str(uuid.uuid4())
            self.cleaned_data["n_irp"] = value
        return value

    def clean_otv_t(self):
        # Ограничение выбора в соответствии с организацией пользователя
        value = self.cleaned_data.get("otv_t")
        return value

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("irp_type") != 2:
            cleaned["zh_d"] = None
        if not cleaned.get("pr_out"):
            cleaned["date_cross"] = None
            cleaned["time_cross"] = None
        date_close = cleaned.get("date_close")
        result = cleaned.get("result")
        if bool(date_close) != bool(result):
            raise forms.ValidationError(
                "Для закрытия обращения одновременно укажите дату и исход."
            )
        date_create = cleaned.get("date_create")
        if date_close and date_create and date_close < date_create:
            self.add_error(
                "date_close", "Дата закрытия не может быть раньше даты поступления."
            )
        return cleaned


class IrpFilterForm(forms.Form):
    """Панель фильтров реестра обращений."""

    id = forms.IntegerField(required=False, label="ID")
    n_irp = forms.CharField(required=False, label="Номер",
                            widget=forms.TextInput(attrs={"data-autocomplete": "n_irp"}))
    z_f = forms.CharField(required=False, label="Фамилия заявителя",
                          widget=forms.TextInput(attrs={"data-autocomplete": "z_f"}))
    z_enp = forms.CharField(required=False, label="ЕНП",
                            widget=forms.TextInput(attrs={"data-autocomplete": "z_enp"}))
    irp_type = forms.ChoiceField(
        required=False, label="Вид обращения", choices=((0, "Все"),) + IRP_TYPES
    )
    how = forms.ChoiceField(
        required=False, label="Способ", choices=((0, "Все"),) + IRP_HOW
    )
    theme = forms.ModelChoiceField(
        queryset=IrpTheme.objects.filter(version=3), required=False, label="Тема"
    )
    date_from = forms.DateField(
        required=False, label="С даты", widget=forms.DateInput(attrs={"type": "date"})
    )
    date_to = forms.DateField(
        required=False, label="По дату", widget=forms.DateInput(attrs={"type": "date"})
    )
    status = forms.ChoiceField(
        required=False,
        label="Статус",
        choices=(
            ("", "Все"),
            ("closed", "Закрыто"),
            ("open", "Открыто"),
            ("overdue", "Просрочено (>30 дней)"),
        ),
    )


class IrpAnswerForm(forms.ModelForm):
    """Форма добавления ответа на обращение (ТЗ п. 215)."""

    class Meta:
        model = IrpAnswer
        fields = ["text", "is_preliminary"]
        widgets = {
            "text": forms.Textarea(
                attrs={"rows": 5, "placeholder": "Текст ответа на обращение"}
            ),
        }

    def clean_text(self):
        text = (self.cleaned_data.get("text") or "").strip()
        if not text:
            raise forms.ValidationError("Укажите текст ответа")
        return text


class IrpRedirectForm(forms.ModelForm):
    """Переадресация обращения (ТЗ п. 212: сопроводительное письмо)."""

    class Meta:
        model = Irp
        fields = [
            "otv_t", "otv_kon", "employee_it", "line_it",
            "pr_out", "date_cross", "time_cross",
        ]
        widgets = {
            "date_cross": forms.DateInput(attrs={"type": "date"}),
            "time_cross": forms.TimeInput(attrs={"type": "time"}),
        }

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["otv_kon"].choices = [
            org for org in ORGS if user.org == 81000 or org[0] == user.org
        ]
        self.fields["employee_it"].queryset = _assignable_employees(
            user, self.instance.employee_it_id
        )

    def clean_date_cross(self):
        value = self.cleaned_data.get("date_cross")
        return value or datetime.date.today()

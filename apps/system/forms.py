"""Формы общесистемных модулей."""

from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import Group

from apps.core.models import EventLog
from apps.core.roles import GROUP_ROLE_MAP, ROLE_GROUP_MAP, SMO_ROLES, TFOMS_ROLES
from apps.employee.models import ORGS, TFOMS, Employee
from apps.system.models import (
    Conversation,
    MessageReply,
    MessageThread,
    NewsItem,
    SystemDocument,
    TaskFile,
    TaskJob,
    TaskNote,
    TaskReport,
)
from apps.system.tasks import TASK_COMMAND_CHOICES
from apps.system.validators import DOC_EXTENSIONS, validate_document_file

# Модули, фиксируемые в журнале событий (для фильтра)
EVENT_MODULE_CHOICES = (
    ("auth", "Вход/выход"),
    ("employee", "Пользователи"),
    ("journal", "Журнал обращений"),
    ("exchange", "Обмен"),
    ("reports", "Отчётность"),
    ("system", "Система"),
)


class EmployeeFilterForm(forms.Form):
    """Поиск в каталоге учётных записей (ТЗ разд. 3.5)."""

    q = forms.CharField(required=False, label="Поиск (ФИО, логин)")
    org = forms.ChoiceField(required=False, label="Организация")
    locked = forms.BooleanField(required=False, label="Только заблокированные")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["org"].choices = [("", "Все")] + [(o, lbl) for o, lbl in ORGS]


class RoleAssignmentMixin:
    """Ограничивает назначение зарегистрированными ролями подходящей организации."""

    def _configure_roles(self):
        self.fields["roles"].queryset = Group.objects.filter(
            name__in=ROLE_GROUP_MAP.values()
        ).order_by("name")

    def clean_roles(self):
        roles = self.cleaned_data.get("roles")
        org = self.cleaned_data.get("org")
        if not roles or org is None:
            return roles
        allowed_codes = TFOMS_ROLES if org == TFOMS else SMO_ROLES
        invalid = [group.name for group in roles if GROUP_ROLE_MAP.get(group.name) not in allowed_codes]
        if invalid:
            raise forms.ValidationError(
                "Роли не соответствуют выбранной организации: " + ", ".join(invalid)
            )
        return roles


class EmployeeCreateForm(RoleAssignmentMixin, UserCreationForm):
    """Регистрация учётной записи пользователя (ТЗ разд. 3.5)."""

    roles = forms.ModelMultipleChoiceField(
        queryset=Group.objects.all(),
        required=False,
        widget=forms.SelectMultiple,
        label="Роли (группы)",
    )

    class Meta(UserCreationForm.Meta):
        model = Employee
        fields = ("username", "last_name", "first_name", "job_title", "org")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._configure_roles()

    def save(self, commit=True):
        user = super().save(commit=commit)
        user.groups.set(self.cleaned_data.get("roles", ()))
        return user


class EmployeeUpdateForm(RoleAssignmentMixin, forms.ModelForm):
    """Редактирование учётной записи: профиль, активность, роли."""

    roles = forms.ModelMultipleChoiceField(
        queryset=Group.objects.all(),
        required=False,
        widget=forms.SelectMultiple,
        label="Роли (группы)",
    )

    class Meta:
        model = Employee
        fields = ("last_name", "first_name", "job_title", "org", "is_active", "is_staff")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._configure_roles()
        if self.instance.pk:
            self.fields["roles"].initial = self.instance.groups.all()

    def save(self, commit=True):
        user = super().save(commit=commit)
        if commit:
            user.groups.set(self.cleaned_data.get("roles", ()))
        return user


class EventFilterForm(forms.Form):
    """Фильтры журнала событий (ТЗ разд. 3.4)."""

    module = forms.ChoiceField(required=False, label="Модуль")
    event_type = forms.ChoiceField(required=False, label="Тип события")
    result = forms.ChoiceField(required=False, label="Результат")
    user = forms.ModelChoiceField(
        queryset=Employee.objects.all(), required=False, label="Инициатор"
    )
    target = forms.CharField(required=False, label="Объект")
    date_from = forms.DateTimeField(required=False, label="С даты",
                                    widget=forms.DateTimeInput(attrs={"type": "datetime-local"}))
    date_to = forms.DateTimeField(required=False, label="По дату",
                                  widget=forms.DateTimeInput(attrs={"type": "datetime-local"}))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["module"].choices = [("", "Все")] + list(EVENT_MODULE_CHOICES)
        self.fields["event_type"].choices = [("", "Все")] + [
            (v, lbl) for v, lbl in EventLog.EventType.choices
        ]
        self.fields["result"].choices = [("", "Все")] + [
            (v, lbl) for v, lbl in EventLog.Result.choices
        ]

    def clean(self):
        cleaned = super().clean()
        start = cleaned.get("date_from")
        end = cleaned.get("date_to")
        if start and end and start > end:
            raise forms.ValidationError(
                "Дата начала периода не может быть позже даты окончания"
            )
        return cleaned


class NewsForm(forms.ModelForm):
    """Новость (ТЗ разд. 3.8, PRD v3 §2.7)."""

    class Meta:
        model = NewsItem
        fields = ("title", "category", "summary", "text", "cover_image", "is_active", "is_pinned")
        widgets = {
            "summary": forms.Textarea(attrs={"rows": 2, "placeholder": "Краткое описание для карточки"}),
            "text": forms.Textarea(attrs={"rows": 10, "placeholder": "Содержание (поддерживаются простые HTML-теги)"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["is_active"].label = "Опубликовано"
        self.fields["category"].empty_label = "Без категории"


class NewConversationForm(forms.ModelForm):
    """Создание диалога/чата (PRD v3 §2.6)."""

    class Meta:
        model = Conversation
        fields = ("title", "participants")
        widgets = {
            "title": forms.TextInput(attrs={"placeholder": "Тема разговора (необязательно)"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["participants"].widget = forms.CheckboxSelectMultiple()
        self.fields["participants"].queryset = Employee.objects.order_by("last_name", "first_name")
        self.fields["participants"].label_from_instance = (
            lambda u: f"{u.full_name()} ({u.get_org_display()})"
        )

    def clean_participants(self):
        qs = self.cleaned_data.get("participants")
        if not qs or not qs.exists():
            raise forms.ValidationError("Выберите хотя бы одного участника")
        return qs


class ThreadForm(forms.ModelForm):
    """Новая тема внутри диалога (PRD v3 §2.6)."""

    class Meta:
        model = MessageThread
        fields = ("title", "is_closed")
        widgets = {
            "title": forms.TextInput(attrs={"placeholder": "Тема обсуждения"}),
        }

    def clean_title(self):
        title = (self.cleaned_data.get("title") or "").strip()
        if not title:
            raise forms.ValidationError("Укажите тему")
        return title


class ReplyForm(forms.ModelForm):
    """Ответ в теме диалога (PRD v3 §2.6)."""

    class Meta:
        model = MessageReply
        fields = ("body",)
        widgets = {
            "body": forms.Textarea(attrs={"rows": 3, "placeholder": "Введите сообщение…"}),
        }

    def clean_body(self):
        body = (self.cleaned_data.get("body") or "").strip()
        if not body:
            raise forms.ValidationError("Введите текст сообщения")
        return body


class DocForm(forms.ModelForm):
    """Загрузка эксплуатационного документа (ТЗ разд. 3.7, PRD v3 §2.8)."""

    class Meta:
        model = SystemDocument
        fields = ("title", "category", "version", "description", "sort_order", "file")
        widgets = {
            "description": forms.Textarea(attrs={"rows": 3}),
        }
        labels = {"sort_order": "Порядок"}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        file_field = self.fields["file"]
        file_field.validators.append(validate_document_file)
        file_field.widget.attrs["accept"] = ",".join(sorted(DOC_EXTENSIONS))
        self.fields["category"].required = False
        self.fields["category"].empty_label = "— Без категории —"
        self.fields["version"].required = False
        self.fields["title"].required = False


class TaskForm(forms.ModelForm):
    """Задание (ТЗ разд. 3.6, PRD v3 §2.11)."""

    class Meta:
        model = TaskJob
        fields = (
            "name", "command", "description",
            "status", "assigned_to", "priority",
            "run_mode", "interval_minutes", "enabled",
        )
        widgets = {
            "description": forms.Textarea(attrs={"rows": 3}),
        }
        labels = {"assigned_to": "Исполнитель"}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["command"].choices = TASK_COMMAND_CHOICES
        self.fields["interval_minutes"].help_text = "Интервал автозапуска в минутах"
        self.fields["interval_minutes"].required = False
        self.fields["priority"].help_text = "0 — низкий, 1 — средний, 2 — высокий"
        self.fields["priority"].required = False
        self.fields["status"].required = False
        self.fields["assigned_to"].queryset = Employee.objects.order_by(
            "last_name", "first_name"
        )
        self.fields["assigned_to"].label_from_instance = (
            lambda u: f"{u.last_name} {u.first_name}".strip() or u.username
        )

    def clean(self):
        cleaned = super().clean()
        if (
            cleaned.get("run_mode") == TaskJob.RunMode.SCHEDULED
            and not cleaned.get("interval_minutes")
        ):
            raise forms.ValidationError(
                {"interval_minutes": "Для задания «По расписанию» укажите интервал"}
            )
        return cleaned


class TaskNoteForm(forms.ModelForm):
    """Заметка к задаче (PRD v3 §2.11)."""

    class Meta:
        model = TaskNote
        fields = ("text",)
        widgets = {
            "text": forms.Textarea(
                attrs={"rows": 2, "placeholder": "Текст заметки", "data-validate": ""}
            ),
        }


class TaskFileForm(forms.ModelForm):
    """Вложение к задаче (PRD v3 §2.11)."""

    class Meta:
        model = TaskFile
        fields = ("file",)
        widgets = {
            "file": forms.ClearableFileInput(attrs={"accept": ".pdf,.docx,.doc,.xlsx,.xls,.zip,txt,.csv"}),
        }


class TaskReportForm(forms.ModelForm):
    """Отчёт по задаче (PRD v3 §2.11)."""

    class Meta:
        model = TaskReport
        fields = ("title", "content")
        widgets = {
            "content": forms.Textarea(attrs={"rows": 5}),
        }

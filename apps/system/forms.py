"""Формы общесистемных модулей."""

from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import Group
from django.db.models import Q

from apps.core.models import EventLog
from apps.core.roles import GROUP_ROLE_MAP, ROLE_GROUP_MAP, SMO_ROLES, TFOMS_ROLES, Roles
from apps.employee.models import ORGS, TFOMS, Employee
from apps.system.models import (
    Conversation,
    MessageReply,
    MessageThread,
    NewsItem,
    SystemDocument,
    TaskAction,
    TaskFile,
    TaskJob,
    TaskNote,
    TaskReport,
)
from apps.system.tasks import get_task_command, task_command_choices, validate_command_params
from apps.system.validators import (
    ALLOWED_ATTACHMENT_EXTENSIONS,
    ALLOWED_DOCUMENT_EXTENSIONS,
    validate_attachment_file,
    validate_document_file,
)

# модули журнала событий
EVENT_MODULE_CHOICES = (
    ("auth", "Вход/выход"),
    ("employee", "Пользователи"),
    ("journal", "Регистрация обращений"),
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
        self.fields["additional_groups"].queryset = Group.objects.exclude(
            name__in=ROLE_GROUP_MAP.values()
        ).order_by("name")

    def _save_groups(self, user):
        roles = self.cleaned_data.get("roles", ())
        additional = self.cleaned_data.get("additional_groups", ())
        user.groups.set([*roles, *additional])

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
    additional_groups = forms.ModelMultipleChoiceField(
        queryset=Group.objects.none(),
        required=False,
        widget=forms.SelectMultiple,
        label="Дополнительные группы",
    )

    class Meta(UserCreationForm.Meta):
        model = Employee
        fields = ("username", "last_name", "first_name", "job_title", "org")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._configure_roles()

    def save(self, commit=True):
        user = super().save(commit=commit)
        self._save_groups(user)
        return user


class EmployeeUpdateForm(RoleAssignmentMixin, forms.ModelForm):
    """Редактирование учётной записи: профиль, активность, роли."""

    roles = forms.ModelMultipleChoiceField(
        queryset=Group.objects.all(),
        required=False,
        widget=forms.SelectMultiple,
        label="Роли (группы)",
    )
    additional_groups = forms.ModelMultipleChoiceField(
        queryset=Group.objects.none(),
        required=False,
        widget=forms.SelectMultiple,
        label="Дополнительные группы",
    )

    class Meta:
        model = Employee
        fields = ("last_name", "first_name", "job_title", "org", "is_active", "is_staff")

    def __init__(self, *args, actor=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.actor = actor
        self._configure_roles()
        if self.instance.pk:
            self.fields["roles"].initial = self.instance.groups.filter(
                name__in=ROLE_GROUP_MAP.values()
            )
            self.fields["additional_groups"].initial = self.instance.groups.exclude(
                name__in=ROLE_GROUP_MAP.values()
            )

    def clean(self):
        cleaned = super().clean()
        if not self.actor or self.instance.pk != self.actor.pk:
            return cleaned

        if not cleaned.get("is_active"):
            self.add_error(
                "is_active",
                "Нельзя отключить собственную учётную запись.",
            )

        roles = cleaned.get("roles")
        admin_group = ROLE_GROUP_MAP[Roles.ADMIN]
        if (
            not self.actor.is_superuser
            and roles is not None
            and not roles.filter(name=admin_group).exists()
        ):
            self.add_error(
                "roles",
                "Нельзя снять собственную роль администратора.",
            )
        return cleaned

    def save(self, commit=True):
        user = super().save(commit=commit)
        if commit:
            self._save_groups(user)
        return user


class UserGroupForm(forms.ModelForm):
    """Произвольная организационная группа без неявных системных прав."""

    class Meta:
        model = Group
        fields = ("name",)

    def clean_name(self):
        name = (self.cleaned_data.get("name") or "").strip()
        if not name:
            raise forms.ValidationError("Укажите наименование группы.")
        if name in ROLE_GROUP_MAP.values():
            raise forms.ValidationError("Это имя зарезервировано системной ролью.")
        duplicate = Group.objects.filter(name__iexact=name)
        if self.instance.pk:
            duplicate = duplicate.exclude(pk=self.instance.pk)
        if duplicate.exists():
            raise forms.ValidationError("Группа с таким наименованием уже существует.")
        return name


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

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["participants"].widget = forms.CheckboxSelectMultiple()
        participants = Employee.objects.filter(is_active=True)
        if user is not None:
            participants = participants.exclude(pk=user.pk)
        self.fields["participants"].queryset = participants.order_by(
            "last_name", "first_name"
        )
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
        fields = ("title",)
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

    attachment = forms.FileField(
        required=False,
        validators=[validate_attachment_file],
        widget=forms.ClearableFileInput(
            attrs={"accept": ",".join(sorted(ALLOWED_ATTACHMENT_EXTENSIONS))}
        ),
        label="Вложение (необязательно)",
    )

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
        file_field.widget.attrs["accept"] = ",".join(
            sorted(ALLOWED_DOCUMENT_EXTENSIONS)
        )
        self.fields["category"].required = False
        self.fields["category"].empty_label = "— Без категории —"
        self.fields["version"].required = False
        self.fields["title"].required = False


class TaskForm(forms.ModelForm):
    """Задание (ТЗ разд. 3.6, PRD v3 §2.11)."""

    command = forms.ChoiceField(
        choices=(),
        label="Действие",
    )

    class Meta:
        model = TaskJob
        fields = (
            "name", "command", "description",
            "assigned_to", "priority",
            "run_mode", "interval_minutes", "max_retries", "retry_delay_seconds",
            "enabled",
        )
        widgets = {
            "description": forms.Textarea(attrs={"rows": 3}),
        }
        labels = {"assigned_to": "Исполнитель"}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        builtin_choices = list(task_command_choices())
        custom_actions = TaskAction.objects.filter(is_active=True).order_by("name")
        if self.instance.pk and str(self.instance.command).startswith("custom:"):
            action_id = str(self.instance.command).split(":", 1)[1]
            if action_id.isdigit():
                custom_actions = custom_actions | TaskAction.objects.filter(pk=action_id)
        custom_choices = [
            (action.command_code, f"{action.name} (пользовательское)")
            for action in custom_actions.distinct()
        ]
        self.fields["command"].choices = builtin_choices + custom_choices
        self.fields["interval_minutes"].help_text = "Интервал автозапуска в минутах"
        self.fields["interval_minutes"].required = False
        self.fields["max_retries"].widget.attrs.update({"min": 0, "max": 10})
        self.fields["retry_delay_seconds"].widget.attrs.update({"min": 0, "max": 86400})
        self.fields["max_retries"].required = False
        self.fields["retry_delay_seconds"].required = False
        self.fields["max_retries"].help_text = "От 0 до 10 повторов после ошибки."
        self.fields["retry_delay_seconds"].help_text = "Пауза между попытками, до 24 часов."
        self.fields["priority"].help_text = "0 — низкий, 1 — средний, 2 — высокий"
        self.fields["priority"].required = False
        available_assignees = Q(is_active=True)
        if self.instance.assigned_to_id:
            available_assignees |= Q(pk=self.instance.assigned_to_id)
        self.fields["assigned_to"].queryset = Employee.objects.filter(
            available_assignees
        ).order_by(
            "last_name", "first_name"
        )
        self.fields["assigned_to"].label_from_instance = (
            lambda u: (
                f"{u.full_name() or u.username} ({u.get_org_display()})"
            )
        )
        self.fields["assigned_to"].widget.attrs["hidden"] = True
        self.task_parameter_fields = []
        for command_code, _label in task_command_choices():
            definition = get_task_command(command_code)
            for parameter in definition.parameters:
                field_name = f"param__{command_code}__{parameter.key}"
                common = {
                    "required": parameter.required,
                    "label": parameter.label,
                    "help_text": parameter.help_text,
                    "initial": (self.instance.params or {}).get(parameter.key, parameter.default)
                    if self.instance.pk and self.instance.command == command_code
                    else parameter.default,
                }
                if parameter.kind == "boolean":
                    field = forms.BooleanField(**common)
                elif parameter.kind == "integer":
                    field = forms.IntegerField(
                        min_value=parameter.minimum, max_value=parameter.maximum, **common
                    )
                elif parameter.kind == "multi_choice":
                    field = forms.MultipleChoiceField(
                        choices=parameter.choices, widget=forms.CheckboxSelectMultiple, **common
                    )
                else:
                    field = forms.CharField(**common)
                self.fields[field_name] = field
                self.task_parameter_fields.append({
                    "command": command_code,
                    "kind": parameter.kind,
                    "field": self[field_name],
                })

    def clean(self):
        cleaned = super().clean()
        if (
            self.instance.pk
            and self.instance.status == TaskJob.Status.CANCELLED
            and cleaned.get("enabled")
        ):
            self.instance.status = TaskJob.Status.CREATED
        if (
            cleaned.get("run_mode") == TaskJob.RunMode.SCHEDULED
            and not cleaned.get("interval_minutes")
        ):
            raise forms.ValidationError(
                {"interval_minutes": "Для задания «По расписанию» укажите интервал"}
            )
        if cleaned.get("run_mode") == TaskJob.RunMode.MANUAL:
            cleaned["interval_minutes"] = None
        retries = cleaned.get("max_retries")
        delay = cleaned.get("retry_delay_seconds")
        if retries is None:
            retries = cleaned["max_retries"] = 2
        if delay is None:
            delay = cleaned["retry_delay_seconds"] = 60
        if retries is not None and not 0 <= retries <= 10:
            self.add_error("max_retries", "Допустимо от 0 до 10 повторов.")
        if delay is not None and not 0 <= delay <= 86400:
            self.add_error("retry_delay_seconds", "Допустимо от 0 до 86 400 секунд.")
        command = cleaned.get("command")
        if command:
            if str(command).startswith("custom:"):
                action_id = str(command).split(":", 1)[1]
                if not action_id.isdigit() or not TaskAction.objects.filter(pk=action_id, is_active=True).exists():
                    self.add_error("command", "Выберите доступное действие.")
                cleaned["params"] = {}
                return cleaned
            definition = get_task_command(command)
            submitted_names = {
                f"param__{command}__{parameter.key}" for parameter in definition.parameters
            }
            if self.is_bound and not any(name in self.data for name in submitted_names) and self.instance.pk:
                cleaned["params"] = dict(self.instance.params or {})
            else:
                raw_params = {
                    parameter.key: cleaned.get(f"param__{command}__{parameter.key}")
                    for parameter in definition.parameters
                }
                try:
                    cleaned["params"] = validate_command_params(command, raw_params)
                except forms.ValidationError as exc:
                    self.add_error(None, exc)
        return cleaned

    def save(self, commit=True):
        self.instance.params = self.cleaned_data.get("params", {})
        return super().save(commit=commit)


class TaskActionForm(forms.ModelForm):
    """Создание пользовательского действия для задач."""

    class Meta:
        model = TaskAction
        fields = (
            "name",
            "action_type",
            "condition_logic",
            "condition_status",
            "condition_org",
            "close_result",
            "description",
        )
        widgets = {
            "name": forms.TextInput(attrs={"placeholder": "Например: Проверка выгрузки"}),
            "description": forms.Textarea(
                attrs={
                    "rows": 3,
                    "placeholder": "Что должен сделать исполнитель или что попадёт в журнал выполнения",
                }
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["action_type"].required = False
        self.fields["condition_logic"].required = False
        self.fields["condition_status"].required = False
        self.fields["condition_status"].choices = [("", "Не учитывать статус")] + list(
            TaskAction.AppealStatus.choices
        )
        self.fields["condition_org"].required = False
        self.fields["condition_org"].choices = [("", "Любая организация")] + list(ORGS)
        self.fields["close_result"].required = False
        self.fields["close_result"].choices = [("", "Рассмотрено обращение")] + list(
            self.fields["close_result"].choices
        )
        self.fields["description"].help_text = (
            "Для ручного действия это инструкция исполнителю; для закрытия обращений — пояснение в журнале запуска."
        )

    def clean_name(self):
        name = (self.cleaned_data.get("name") or "").strip()
        if not name:
            raise forms.ValidationError("Укажите наименование действия.")
        duplicate = TaskAction.objects.filter(name__iexact=name)
        if self.instance.pk:
            duplicate = duplicate.exclude(pk=self.instance.pk)
        if duplicate.exists():
            raise forms.ValidationError("Действие с таким названием уже есть.")
        return name

    def clean(self):
        cleaned = super().clean()
        cleaned["action_type"] = cleaned.get("action_type") or TaskAction.ActionType.MANUAL
        cleaned["condition_logic"] = (
            cleaned.get("condition_logic") or TaskAction.ConditionLogic.ALL
        )
        if cleaned.get("action_type") == TaskAction.ActionType.CLOSE_APPEALS:
            has_condition = bool(
                cleaned.get("condition_status") or cleaned.get("condition_org")
            )
            if not has_condition:
                raise forms.ValidationError(
                    "Для массового закрытия укажите хотя бы одно условие отбора."
                )
        else:
            cleaned["condition_status"] = ""
            cleaned["condition_org"] = None
            cleaned["close_result"] = None
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
            "file": forms.ClearableFileInput(
                attrs={"accept": ",".join(sorted(ALLOWED_ATTACHMENT_EXTENSIONS))}
            ),
        }


class TaskReportForm(forms.ModelForm):
    """Отчёт по задаче (PRD v3 §2.11)."""

    class Meta:
        model = TaskReport
        fields = ("title", "content")
        widgets = {
            "content": forms.Textarea(attrs={"rows": 5}),
        }

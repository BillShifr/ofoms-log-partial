"""Расширяемый реестр действий автоматизированных заданий."""

from collections.abc import Callable
from dataclasses import dataclass

from django.core.exceptions import ValidationError


@dataclass(frozen=True)
class TaskParameter:
    key: str
    label: str
    kind: str = "text"
    required: bool = False
    default: object = None
    choices: tuple = ()
    help_text: str = ""
    minimum: int | None = None
    maximum: int | None = None


@dataclass(frozen=True)
class TaskCommand:
    code: str
    label: str
    handler: Callable[[dict], str]
    description: str
    parameters: tuple[TaskParameter, ...] = ()


_COMMANDS: dict[str, TaskCommand] = {}


def register_task_command(command: TaskCommand) -> None:
    """Регистрирует действие; внешние приложения могут вызывать это при ready()."""
    if command.code in _COMMANDS:
        raise ValueError(f"Команда задания уже зарегистрирована: {command.code}")
    _COMMANDS[command.code] = command


def task_command_choices() -> tuple:
    return tuple((code, command.label) for code, command in _COMMANDS.items())


def task_command_labels() -> dict:
    return dict(task_command_choices())


def get_task_command(command: str) -> TaskCommand:
    try:
        return _COMMANDS[command]
    except KeyError as exc:
        raise ValueError(f"Неизвестная команда задания: {command}") from exc


def validate_command_params(command: str, params: dict | None) -> dict:
    definition = get_task_command(command)
    params = params or {}
    if not isinstance(params, dict):
        raise ValidationError("Параметры действия должны быть объектом.")
    allowed = {parameter.key: parameter for parameter in definition.parameters}
    unknown = sorted(set(params) - set(allowed))
    if unknown:
        raise ValidationError(f"Неизвестные параметры: {', '.join(unknown)}")

    cleaned = {}
    for key, parameter in allowed.items():
        value = params.get(key, parameter.default)
        if parameter.kind == "boolean":
            value = value in (True, "true", "1", "on", 1)
        elif parameter.kind == "integer":
            if value in (None, ""):
                value = parameter.default
            try:
                value = int(value)
            except (TypeError, ValueError) as exc:
                raise ValidationError({key: "Введите целое число."}) from exc
            if parameter.minimum is not None and value < parameter.minimum:
                raise ValidationError({key: f"Минимальное значение: {parameter.minimum}."})
            if parameter.maximum is not None and value > parameter.maximum:
                raise ValidationError({key: f"Максимальное значение: {parameter.maximum}."})
        elif parameter.kind == "multi_choice":
            value = value or []
            if not isinstance(value, (list, tuple)):
                value = [value]
            valid = {choice[0] for choice in parameter.choices}
            if valid and isinstance(next(iter(valid)), int):
                try:
                    value = [int(item) for item in value]
                except (TypeError, ValueError) as exc:
                    raise ValidationError({key: "Выбрано недопустимое значение."}) from exc
            if any(item not in valid for item in value):
                raise ValidationError({key: "Выбрано недопустимое значение."})
        elif value is not None:
            value = str(value).strip()
        if parameter.required and value in (None, "", []):
            raise ValidationError({key: "Обязательный параметр."})
        if value not in (None, "", []):
            cleaned[key] = value
    return cleaned


def _database_health(params):
    from django.db import connection
    from django.db.migrations.executor import MigrationExecutor

    with connection.cursor() as cursor:
        cursor.execute("SELECT 1")
        if cursor.fetchone()[0] != 1:
            raise RuntimeError("База данных вернула неожиданный результат проверки")
    if params.get("check_migrations", True):
        executor = MigrationExecutor(connection)
        pending = executor.migration_plan(executor.loader.graph.leaf_nodes())
        if pending:
            names = ", ".join(
                f"{migration.app_label}.{migration.name}" for migration, _ in pending[:10]
            )
            raise RuntimeError(f"Обнаружены неприменённые миграции: {names}")
    if params.get("check_migrations", True):
        return "Соединение с базой данных доступно; схема данных актуальна."
    return "Соединение с базой данных доступно."


def _cleanup_expired_tokens(params):
    import datetime as _dt

    from apps.core.models import ConsumedToken

    batch_size = params.get("batch_size", 1000)
    ids = list(
        ConsumedToken.objects.filter(
            expires_at__lt=_dt.datetime.now(tz=_dt.UTC)
        )
        .order_by("expires_at")
        .values_list("pk", flat=True)[:batch_size]
    )
    deleted, _ = ConsumedToken.objects.filter(pk__in=ids).delete()
    return f"Удалено истёкших одноразовых токенов: {deleted}."


def _run_exchange_import(params):
    from apps.exchange.importers import import_all

    results = import_all(orgs=params.get("orgs") or None)
    if not results:
        return "Файлов для обработки не найдено."
    return "; ".join(
        f"{result.filename}: ok={result.ok}, записей={result.rows}" for result in results
    )


def _register_builtin_commands():
    from apps.employee.models import ORGS

    register_task_command(TaskCommand(
        code="database_health", label="Проверка базы данных", handler=_database_health,
        description="Проверяет подключение к БД и отсутствие неприменённых миграций.",
        parameters=(TaskParameter(
            key="check_migrations", label="Проверять актуальность схемы",
            kind="boolean", default=True,
        ),),
    ))
    register_task_command(TaskCommand(
        code="expired_token_cleanup", label="Очистка истёкших одноразовых токенов",
        handler=_cleanup_expired_tokens,
        description="Удаляет истёкшие идентификаторы временных JWT ограниченными пакетами.",
        parameters=(TaskParameter(
            key="batch_size", label="Размер пакета", kind="integer", default=1000,
            minimum=1, maximum=10000, help_text="От 1 до 10 000 записей за запуск.",
        ),),
    ))
    register_task_command(TaskCommand(
        code="exchange_import", label="Автозагрузка файлов обмена (XML/Excel)",
        handler=_run_exchange_import,
        description="Импортирует ожидающие файлы обмена для выбранных организаций.",
        parameters=(TaskParameter(
            key="orgs", label="Организации", kind="multi_choice",
            choices=tuple(ORGS), help_text="Без выбора обрабатываются все организации.",
        ),),
    ))


_register_builtin_commands()

TASK_COMMAND_LABELS = task_command_labels()
TASK_COMMAND_CHOICES = task_command_choices()


def run_command(command: str, params: dict | None) -> str:
    if str(command).startswith("custom:"):
        from apps.system.models import TaskAction

        action_id = str(command).split(":", 1)[1]
        try:
            action = TaskAction.objects.get(pk=action_id, is_active=True)
        except (TaskAction.DoesNotExist, ValueError) as exc:
            raise ValidationError("Пользовательское действие недоступно.") from exc
        if action.description:
            return f"Пользовательское действие выполнено: {action.name}. {action.description}"
        return f"Пользовательское действие выполнено: {action.name}."
    definition = get_task_command(command)
    return definition.handler(validate_command_params(command, params))

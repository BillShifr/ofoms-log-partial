"""Реестр команд автоматизированных заданий (ТЗ разд. 3.6).

Команда — именованная функция, вызываемая TaskJob.run() с параметрами из
JSON-поля params. Реестр расширяется здесь же; вызов импортируется лениво,
чтобы избежать циклов импорта при старте Django.
"""

TASK_COMMAND_LABELS = {
    "noop": "Проверка доступности задания",
    "exchange_import": "Автозагрузка файлов обмена (XML/Excel)",
}

TASK_COMMAND_CHOICES = tuple((k, v) for k, v in TASK_COMMAND_LABELS.items())


def _noop(_params):
    return "ok"


def _run_exchange_import(params):
    from apps.exchange.importers import import_all

    orgs = (params or {}).get("orgs") or None
    results = import_all(orgs=orgs)
    if not results:
        return "Файлов для обработки не найдено"
    parts = []
    for res in results:
        parts.append(f"{res.filename}: ok={res.ok}, записей={res.rows}")
    return "; ".join(parts)


_COMMANDS = {
    "noop": _noop,
    "exchange_import": _run_exchange_import,
}


def run_command(command: str, params: dict) -> str:
    """Выполняет команду реестра; возвращает строку лога."""
    try:
        func = _COMMANDS[command]
    except KeyError as exc:
        raise ValueError(f"Неизвестная команда задания: {command}") from exc
    return func(params)

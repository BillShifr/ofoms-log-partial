"""Canonical metadata for configurable portal tables."""

from apps.core.policy import CAPABILITY_LABELS
from apps.reports.reports import REPORT_INDEX


def _columns(*items):
    return [
        {"key": key, "label": label, "group": group, "sortable": sortable}
        for key, label, group, sortable in items
    ]


TABLES = {
    "system-tasks": {
        "title": "Автоматизированные задания",
        "columns": _columns(
            ("name", "Наименование", "Задание", True),
            ("command", "Действие", "Задание", True),
            ("status", "Статус", "Состояние", True),
            ("assigned_to", "Исполнитель", "Ответственность", True),
            ("priority", "Приоритет", "Ответственность", True),
            ("run_mode", "Режим", "Запуск", True),
            ("last_finished_at", "Последний запуск", "Запуск", True),
            ("last_result", "Результат", "Запуск", True),
            ("actions", "Действия", "", False),
        ),
    },
    "system-task-runs": {
        "title": "История запусков",
        "columns": _columns(
            ("started_at", "Начало", "Период", True),
            ("finished_at", "Завершение", "Период", True),
            ("triggered_by", "Инициатор", "Запуск", True),
            ("result", "Результат", "Запуск", True),
            ("log", "Лог", "Запуск", False),
        ),
    },
    "exchange-logs": {
        "title": "Загрузки обмена",
        "columns": _columns(
            ("filename", "Файл", "Загрузка", True),
            ("org", "Организация", "Загрузка", True),
            ("kind", "Тип", "Загрузка", True),
            ("status", "Статус", "Результат", True),
            ("rows", "Записей", "Результат", True),
            ("created_at", "Когда", "Период", True),
            ("actions", "Действия", "", False),
        ),
    },
    "exchange-protocol": {
        "title": "Протокол ФЛК",
        "columns": _columns(
            ("code", "Код", "Ошибка", True),
            ("field", "Поле", "Ошибка", True),
            ("irp", "Обращение", "Запись", True),
            ("comment", "Комментарий", "Ошибка", False),
        ),
    },
    "system-events": {
        "title": "Журнал событий",
        "columns": _columns(
            ("id", "ID", "Событие", True),
            ("started_at", "Начало", "Период", True),
            ("finished_at", "Завершение", "Период", True),
            ("event_type", "Тип", "Событие", True),
            ("module", "Модуль", "Событие", True),
            ("result", "Результат", "Событие", True),
            ("user", "Инициатор", "Участник", True),
            ("target", "Объект", "Событие", True),
            ("ip", "IP", "Технические данные", True),
            ("duration", "Длит., мс", "Технические данные", True),
        ),
    },
    "system-users": {
        "title": "Пользователи",
        "columns": _columns(
            ("full_name", "ФИО", "Учётная запись", True),
            ("username", "Логин", "Учётная запись", True),
            ("org", "Организация", "Работа", True),
            ("job_title", "Должность", "Работа", True),
            ("roles", "Роли (группы)", "Доступ", False),
            ("status", "Статус", "Доступ", True),
            ("actions", "Действия", "", False),
        ),
    },
    "system-capabilities": {
        "title": "Матрица прав ролей",
        "columns": [
            {"key": "role", "label": "Роль", "group": "", "sortable": False},
            *[
                {
                    "key": f"capability_{index}",
                    "label": label,
                    "group": "Права",
                    "sortable": False,
                }
                for index, label in enumerate(CAPABILITY_LABELS.values())
            ],
        ],
    },
    "journal-history": {
        "title": "История изменений",
        "columns": _columns(
            ("created_at", "Дата", "Изменение", True),
            ("user", "Пользователь", "Изменение", True),
            ("field", "Поле", "Изменение", True),
            ("old", "Было", "Значение", False),
            ("new", "Стало", "Значение", False),
        ),
    },
}


def get_table_meta(table_key: str):
    """Return static metadata or build it for a concrete report table."""
    meta = TABLES.get(table_key)
    if meta is not None:
        return meta
    if table_key.startswith("report-"):
        report = REPORT_INDEX.get(table_key.removeprefix("report-"))
        if report is not None:
            return {
                "title": f"Результат отчёта «{report.title}»",
                "columns": _columns(
                    *((key, label, "Отчёт", True) for key, label in report.columns)
                ),
            }
    return None


def allowed_sorts(meta: dict) -> set[str]:
    return {column["key"] for column in meta["columns"] if column["sortable"]}

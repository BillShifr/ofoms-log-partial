"""Метаданные колонок таблицы журнала для персональной настройки (ТЗ разд. 3.2).

Каждая колонка: key (техническое имя), label, group (логическая группа для
настроек), sortable (поддержка сортировки по реквизиту).
"""

JOURNAL_TABLE_KEY = "journal"

JOURNAL_COLUMNS = [
    {"key": "id", "label": "ID", "group": "", "sortable": True},
    {"key": "n_irp", "label": "УНр", "group": "Обращение", "sortable": False},
    {"key": "irp_type", "label": "Вид", "group": "Обращение", "sortable": True},
    {"key": "theme", "label": "Тема", "group": "Обращение", "sortable": False},
    {"key": "date_create", "label": "Поступило", "group": "Периоды", "sortable": True},
    {"key": "data_plan", "label": "Срок рассм.", "group": "Периоды", "sortable": True},
    {"key": "date_close", "label": "Закрыто", "group": "Периоды", "sortable": True},
    {"key": "z_f", "label": "Заявитель", "group": "Заявитель / застрахованный", "sortable": True},
    {"key": "z_enp", "label": "ЕНП", "group": "Заявитель / застрахованный", "sortable": True},
    {"key": "employee_one", "label": "Принял", "group": "Исполнение", "sortable": False},
    {"key": "status", "label": "Статус", "group": "", "sortable": False},
]

# доступные пользователю поля сортировки
SORTABLE_FIELDS = {
    c["key"]: c
    for c in JOURNAL_COLUMNS
    if c["sortable"]
}

# поля и выражения сортировки в базе
ALLOWED_SORTS = {
    "id", "-id",
    "date_create", "-date_create",
    "data_plan", "-data_plan",
    "date_close", "-date_close",
    "irp_type", "-irp_type",
    "z_f", "-z_f",
    "z_enp", "-z_enp",
}

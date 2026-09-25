"""Ролевая модель v2 (RBAC).

Роли закреплены письмом ФФОМС от 26.02.2021 № 00-10-30-04/1101 (п. 10–16)
и совпадают с константой LINES из v1 (journal.models.LINES). Роли реализуются
как группы Django; маппинг имя-группы <-> код роли задан здесь.
"""

# коды ролей сохраняют совместимость с v1
class Roles:
    OP1 = 1
    OP2 = 2
    SP1 = 3
    SP2 = 4
    SP3 = 5
    ADMIN = 6
    CALL_ADMIN = 7  # администратор контактного центра


ROLE_CHOICES = (
    (Roles.OP1, "ОП1 — оператор 1 уровня"),
    (Roles.OP2, "ОП2 — оператор 2 уровня"),
    (Roles.SP1, "СП1 — страховой представитель 1 уровня"),
    (Roles.SP2, "СП2 — страховой представитель 2 уровня"),
    (Roles.SP3, "СП3 — страховой представитель 3 уровня"),
    (Roles.ADMIN, "Администратор системы"),
    (Roles.CALL_ADMIN, "Администратор контакт-центра"),
)

# имя группы django для кода роли
ROLE_GROUP_MAP = {
    Roles.OP1: "ОП1",
    Roles.OP2: "ОП2",
    Roles.SP1: "СП1",
    Roles.SP2: "СП2",
    Roles.SP3: "СП3",
    Roles.ADMIN: "Администратор",
    Roles.CALL_ADMIN: "Администратор контакт-центра",
}

# код роли по имени группы
GROUP_ROLE_MAP = {v: k for k, v in ROLE_GROUP_MAP.items()}

# роли тфомс
TFOMS_ROLES = {Roles.OP1, Roles.OP2, Roles.ADMIN, Roles.CALL_ADMIN}

# роли смо
SMO_ROLES = {Roles.SP1, Roles.SP2, Roles.SP3}


def role_code_for_user(user) -> int | None:
    """Первичная роль в каноническом порядке (или None)."""
    if user is None or not user.is_authenticated:
        return None
    names = set(
        user.groups.filter(name__in=ROLE_GROUP_MAP.values()).values_list(
            "name", flat=True
        )
    )
    for code, name in ROLE_GROUP_MAP.items():
        if name in names:
            return code
    return None


def ensure_role_groups():
    """Создаёт группы-роли при миграции/запуске (идемпотентно)."""
    from django.contrib.auth.models import Group

    for group_name in ROLE_GROUP_MAP.values():
        Group.objects.get_or_create(name=group_name)

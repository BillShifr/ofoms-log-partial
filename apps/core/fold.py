"""Регистронезависимый поиск по кириллице/латинице, не зависящий от локали БД.

PostgreSQL в локали C/POSIX не сворачивает регистр не-ASCII символов:
`LOWER`/`ILIKE`/`citext` работают только для ASCII. Чтобы искать
"иван" -> "Иван" в любой локали, обе стороны сравнения приводятся к
нижнему регистру функцией SQL `translate` (посимвольная замена), затем
выполняется поиск подстроки через `strpos` (без wildcard-символов LIKE).

Требование: PRD v3 §2.3.2 (фильтры журнала), §2.9.1 (поиск пользователей),
§2.10 (журнал событий).
"""

from django.db.models import F, Func, Q, Value

_UPPER = (
    "АБВГДЕЁЖЗИЙКЛМНОПРСТУФХЦЧШЩЪЫЬЭЮЯ"
    "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
)
_LOWER = (
    "абвгдеёжзийклмнопрстуфхцчшщъыьэюя"
    "abcdefghijklmnopqrstuvwxyz"
)
_TRANS = str.maketrans(_UPPER, _LOWER)


def fold(value):
    """Сворачивает строку в нижний регистр (кириллица + латиница)."""
    if not value:
        return ""
    return value.translate(_TRANS)


def _fold_sql(expr):
    """SQL-выражение `translate(<expr>, ВЕРХ, низ)`."""
    return Func(expr, Value(_UPPER), Value(_LOWER), function="translate")


def contains_folded(qs, field, value, alias):
    """Фильтрует qs: поле содержит value без учёта регистра.

    Работает в любой локали PostgreSQL (в т.ч. C/POSIX). Поиск подстроки
    через SQL `strpos`, поэтому `%`/`_` не трактуются как шаблонные символы.

    Параметр `alias` задаёт уникальное имя аннотации (одна аннотация на
    поле в пределах одного запроса).
    """
    v = fold(value).strip()
    if not v:
        return qs
    qs = qs.annotate(
        **{alias: Func(_fold_sql(F(field)), Value(v), function="strpos")}
    )
    return qs.filter(**{f"{alias}__gt": 0})


def filter_contains_any(qs, fields, value, prefix="fold"):
    """Фильтрует qs: хотя бы одно из полей содержит value без учёта регистра.

    Аналог OR по `__icontains`, но со сворачиванием кириллицы/латиницы в
    любой локали PostgreSQL. `prefix` задаёт префикс имён аннотаций — при
    последовательных вызовах (несколько слов запроса) используйте разные
    префиксы для избежания коллизий.
    """
    v = fold(value).strip()
    if not v:
        return qs
    ann, q = {}, Q()
    for i, field in enumerate(fields):
        alias = f"{prefix}{i}"
        ann[alias] = Func(_fold_sql(F(field)), Value(v), function="strpos")
        q |= Q(**{f"{alias}__gt": 0})
    return qs.annotate(**ann).filter(q)

"""Безопасная подготовка пользовательских значений для файлов экспорта."""


_FORMULA_PREFIXES = ("=", "+", "-", "@")


def excel_safe_value(value):
    """Не позволяет строке стать формулой при открытии XLSX в табличном редакторе."""
    if not isinstance(value, str):
        return value
    candidate = value.lstrip(" \t\r\n")
    if candidate.startswith(_FORMULA_PREFIXES):
        return f"'{value}"
    return value

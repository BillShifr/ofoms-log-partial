"""Транзакционно-безопасные операции с файловым хранилищем."""

from django.db import transaction
from django.http import Http404


def open_field_file_or_404(field_file):
    """Открывает storage object, не раскрывая внутреннюю ошибку пользователю."""
    try:
        return field_file.open("rb")
    except (FileNotFoundError, OSError):
        raise Http404("Файл недоступен.") from None


def delete_field_file_after_commit(field_file) -> None:
    """Удаляет сохранённый файл только после успешного commit текущей транзакции."""
    if not field_file or not field_file.name:
        return
    storage = field_file.storage
    name = field_file.name
    transaction.on_commit(lambda: storage.delete(name))

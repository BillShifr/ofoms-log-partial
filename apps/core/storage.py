"""Транзакционно-безопасные операции с файловым хранилищем."""

from django.db import transaction


def delete_field_file_after_commit(field_file) -> None:
    """Удаляет сохранённый файл только после успешного commit текущей транзакции."""
    if not field_file or not field_file.name:
        return
    storage = field_file.storage
    name = field_file.name
    transaction.on_commit(lambda: storage.delete(name))

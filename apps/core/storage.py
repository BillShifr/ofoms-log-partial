"""Транзакционно-безопасные операции с файловым хранилищем."""

from contextlib import contextmanager

from django.db import transaction
from django.http import Http404


class UploadedFileRollback:
    """Удаляет новый storage object, если окружающая операция не завершилась."""

    def __init__(self):
        self.field_file = None

    def track(self, field_file) -> None:
        """Начинает отслеживать FileField до вызова model.save()."""
        self.field_file = field_file

    def __enter__(self):
        return self

    def __exit__(self, exc_type, _exc_value, _traceback):
        if (
            exc_type is not None
            and self.field_file is not None
            and self.field_file._committed
        ):
            self.field_file.delete(save=False)
        return False


def open_field_file_or_404(field_file):
    """Открывает storage object, не раскрывая внутреннюю ошибку пользователю."""
    try:
        return field_file.open("rb")
    except (FileNotFoundError, OSError):
        raise Http404("Файл недоступен.") from None


@contextmanager
def close_file_on_error(file_handle):
    """Закрывает handle, пока владение ещё не передано streaming response."""
    try:
        yield file_handle
    except BaseException:
        file_handle.close()
        raise


def delete_field_file_after_commit(field_file) -> None:
    """Удаляет сохранённый файл только после успешного commit текущей транзакции."""
    if not field_file or not field_file.name:
        return
    storage = field_file.storage
    name = field_file.name
    transaction.on_commit(lambda: storage.delete(name))

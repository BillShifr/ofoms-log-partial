"""Потоковые ограничения входящих файлов до model/form validation."""

from django.core.files.uploadhandler import FileUploadHandler, StopUpload

MAX_UPLOAD_SIZE_BYTES = 200 * 1024 * 1024


class BoundedUploadHandler(FileUploadHandler):
    """Останавливает multipart, прежде чем файл переполнит временный том."""

    def new_file(self, *args, **kwargs):
        super().new_file(*args, **kwargs)
        if self.content_length is not None and self.content_length > MAX_UPLOAD_SIZE_BYTES:
            self._reject()

    def receive_data_chunk(self, raw_data, start):
        if start + len(raw_data) > MAX_UPLOAD_SIZE_BYTES:
            self._reject()
        return raw_data

    def file_complete(self, file_size):
        return None

    def _reject(self):
        self.request.upload_size_limit_exceeded = True
        raise StopUpload(connection_reset=False)

"""Валидаторы системных загрузок (Этап 7, безопасность 2 класс ФСТЭК)."""

import os

from django.core.exceptions import ValidationError

DOC_EXTENSIONS = {
    ".pdf",
    ".doc",
    ".docx",
    ".xls",
    ".xlsx",
    ".odt",
    ".ods",
    ".rtf",
    ".txt",
    ".zip",
}
VIDEO_EXTENSIONS = {".mp4", ".ogv", ".webm"}
ALLOWED_DOCUMENT_EXTENSIONS = DOC_EXTENSIONS | VIDEO_EXTENSIONS
DOC_MAX_SIZE_MB = 20
DOC_MAX_SIZE_BYTES = DOC_MAX_SIZE_MB * 1024 * 1024
VIDEO_MAX_SIZE_MB = 200
VIDEO_MAX_SIZE_BYTES = VIDEO_MAX_SIZE_MB * 1024 * 1024
IMAGE_EXTENSIONS = {".gif", ".jpeg", ".jpg", ".png", ".webp"}
IMAGE_MAX_SIZE_MB = 10
IMAGE_MAX_SIZE_BYTES = IMAGE_MAX_SIZE_MB * 1024 * 1024


def validate_document_file(value):
    ext = os.path.splitext(value.name)[1].lower()
    if ext not in ALLOWED_DOCUMENT_EXTENSIONS:
        raise ValidationError(
            f"Недопустимый тип файла: «{ext or '(без расширения)'}». "
            f"Разрешены: {', '.join(sorted(ALLOWED_DOCUMENT_EXTENSIONS))}."
        )
    max_size = VIDEO_MAX_SIZE_BYTES if ext in VIDEO_EXTENSIONS else DOC_MAX_SIZE_BYTES
    max_size_mb = VIDEO_MAX_SIZE_MB if ext in VIDEO_EXTENSIONS else DOC_MAX_SIZE_MB
    if value.size > max_size:
        raise ValidationError(f"Размер файла не должен превышать {max_size_mb} МБ.")


def validate_image_file(value):
    """Ограничивает объём и расширение загружаемых обложек новостей."""
    ext = os.path.splitext(value.name)[1].lower()
    if ext not in IMAGE_EXTENSIONS:
        raise ValidationError(
            f"Недопустимый тип изображения: «{ext or '(без расширения)'}». "
            f"Разрешены: {', '.join(sorted(IMAGE_EXTENSIONS))}."
        )
    if value.size > IMAGE_MAX_SIZE_BYTES:
        raise ValidationError(
            f"Размер изображения не должен превышать {IMAGE_MAX_SIZE_MB} МБ."
        )

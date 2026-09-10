"""Валидаторы паролей (ТЗ разд. 3.1): политика стойкости пароля.

Требование: не менее 8 символов; строчные и прописные буквы, цифры,
специальные символы. Дополнительно Django-валидаторы заданы в settings.
"""

import re

from django.core.exceptions import ValidationError
from django.utils.translation import gettext as _


class ComplexityPasswordValidator:
    """Проверка наличия всех четырёх классов символов."""

    CLASSES = [
        (re.compile(r"[a-zа-яё]"), "строчные буквы"),
        (re.compile(r"[A-ZА-ЯЁ]"), "прописные буквы"),
        (re.compile(r"\d"), "цифры"),
        (re.compile(r"[^\w\s]"), "специальные символы"),
    ]

    def validate(self, password, user=None):
        missing = [label for pattern, label in self.CLASSES if not pattern.search(password)]
        if missing:
            raise ValidationError(
                _("Пароль должен содержать: %(items)s."),
                code="password_missing_classes",
                params={"items": ", ".join(missing)},
            )

    def get_help_text(self):
        return _(
            "Пароль должен содержать строчные и прописные буквы, "
            "цифры и специальные символы."
        )

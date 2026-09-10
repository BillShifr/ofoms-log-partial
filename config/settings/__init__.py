"""Настройки Django.

Выбор окружения: DJANGO_SETTINGS_MODULE=config.settings.{dev|prod}.
По умолчанию — dev локально (manage.py), prod — в контейнере.
"""

import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.dev")

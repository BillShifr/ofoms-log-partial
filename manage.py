#!/usr/bin/env python
"""Утилита командной строки Django для v2."""

import os
import sys


def main():
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.dev")
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError(
            "Не удалось импортировать Django. Убедитесь, что он установлен "
            "и доступен в PYTHONPATH (см. README, uv sync)."
        ) from exc
    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()

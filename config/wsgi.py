"""WSGI-точка входа для gunicorn.

Проект: config.settings (см. config/settings/__init__.py). Модуль подключается
в Dockerfile -> CMD ["gunicorn","config.wsgi:application",...].
"""

import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.prod")

from django.core.wsgi import get_wsgi_application  # noqa: E402

application = get_wsgi_application()

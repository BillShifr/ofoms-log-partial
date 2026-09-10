"""ASGI-точка входа (на будущее, если понадобятся WebSocket/фоновые задачи)."""

import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.prod")

from django.core.asgi import get_asgi_application  # noqa: E402

application = get_asgi_application()

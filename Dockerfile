FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Системная библиотека для psycopg 3 (libpq)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Сначала копируем файлы зависимостей — слой кешируется (пересборка быстрее)
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev

COPY . .
RUN uv sync --frozen --no-dev && \
    chmod +x .venv/bin/gunicorn && \
    .venv/bin/python manage.py collectstatic --noinput --settings config.settings.prod && \
    mkdir -p /app/media /app/exchange/in /app/exchange/out /app/exchange/archive

EXPOSE 8000

ENV DJANGO_SETTINGS_MODULE=config.settings.prod

CMD ["/app/.venv/bin/gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "3", "--timeout", "60"]
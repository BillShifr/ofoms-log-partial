FROM ghcr.io/astral-sh/uv@sha256:b485bd65cc2cf1c9a93b3554012c9c3778cf7b1b5fd3d3096ce9e1226c97e1e6 AS uv-tools

FROM python:3.13-slim@sha256:9d2e5553305c7c7b0097999bb17187c69b921ccd6bc9d40e4bb5ebe652c00285

ARG VCS_REF=unknown
LABEL org.opencontainers.image.source="https://github.com/BillShifr/ofoms-log-partial" \
      org.opencontainers.image.revision="${VCS_REF}"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

RUN groupadd --gid 10001 app && \
    useradd --uid 10001 --gid app --no-create-home --home-dir /app --shell /usr/sbin/nologin app

# Сначала копируем файлы зависимостей — слой кешируется (пересборка быстрее).
# uv монтируется только на время build step и не остаётся в runtime image.
COPY pyproject.toml uv.lock README.md ./
RUN --mount=from=uv-tools,source=/uv,target=/usr/local/bin/uv \
    --mount=type=cache,target=/root/.cache/uv \
    UV_HTTP_TIMEOUT=60 UV_HTTP_RETRIES=10 uv sync --frozen --no-dev --no-install-project

COPY . .
RUN chmod +x .venv/bin/gunicorn && \
    .venv/bin/python manage.py collectstatic --noinput --settings config.settings.base && \
    mkdir -p /app/media /app/exchange/in /app/exchange/out /app/exchange/archive && \
    chown -R app:app /app/media /app/exchange

EXPOSE 8000

ENV DJANGO_SETTINGS_MODULE=config.settings.prod

USER 10001:10001

CMD ["/app/.venv/bin/gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "3", "--timeout", "60"]

# Единый электронный журнал обращений граждан (v2)

Информационная система ТФОМС ХМАО — Югры для регистрации, учёта и анализа
обращений граждан в системе обязательного медицинского страхования.

## Стек

- Python 3.13, Django 5.2 LTS, PostgreSQL (psycopg 3 + пул)
- Gunicorn + WhiteNoise (статик-хостинг)
- lxml (XSD-контроль файлов обмена), openpyxl (Excel)
- PyJWT (сквозная авторизация), django-import-export, rangefilter

## Быстрый старт (разработка)

```bash
uv sync               # создание .venv + установка зависимостей
cp .env.example .env  # параметры окружения (локальная БД ejournal)
uv run manage.py makemigrations
uv run manage.py migrate
uv run manage.py createsuperuser
uv run manage.py runserver
```

База: PostgreSQL; создать роль/БД заранее:

```sql
CREATE USER ejournal WITH PASSWORD 'ejournal';
CREATE DATABASE ejournal OWNER ejournal;
```

## Запуск в Docker

```bash
docker compose up --build
```

Compose запускает отдельный сервис `scheduler`, который раз в минуту вызывает
`manage.py run_tasks`. Зависшие дольше `TASK_STALE_AFTER_SECONDS` запуски перед
каждым циклом автоматически закрываются с результатом «Ошибка»; для отдельной
диагностики доступна команда `manage.py run_tasks --recover-only`.

## Конфигурация

Настройки — `config/settings/{base,dev,prod}.py`. Переменные окружения
описаны в `.env.example`.

## Документация

- `docs/MAIN-EXTRACT.md` — основная выдержка (источники требований: ТЗ,
  письмо ФФОМС от 26.02.2021 № 00-10-30-04/1101).
- `docs/` — эксплуатационная документация.

## Этапы разработки

1. Каркас и инфраструктура (текущий)
2. Журнал: UI по дизайн-системе ofoms.ru, реестр, карточка, история, печать
3. Обмен: XML/Excel импорт, XSD-контроль, автозагрузка, ФЛК
4. Ролевой доступ и делегирование полномочий
5. Отчётные формы (Приложения №1–9) и сквозная авторизация
6. Служебные модули: задачи, новости, документация, настройки UI
7. Защита информации (ФСТЭК-17) и окончательный аудит
8. Развёртывание и промышленная эксплуатация

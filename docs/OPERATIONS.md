# Установка и промышленная эксплуатация

## Предварительные условия

- Linux-хост с Docker Engine и Docker Compose v2;
- PostgreSQL 14+ при внешнем размещении либо штатный PostgreSQL 16 из Compose;
- TLS-терминатор перед портом приложения;
- отдельные случайные значения `SECRET_KEY` и `JWT_SECRET` длиной не менее 50 символов;
- случайный пароль `DB_PASSWORD` длиной не менее 16 символов, отличный от имени БД и пользователя.

Скопируйте `.env.example` в `.env`, замените все значения `change-me` и укажите публичные имена в `ALLOWED_HOSTS`. Без безопасных `SECRET_KEY`, `JWT_SECRET` и `DB_PASSWORD` production settings и Compose завершаются с ошибкой до запуска сервисов. Production defaults включают secure cookies, HTTPS redirect и HSTS. Если TLS завершается на reverse proxy, он должен передавать запрос приложению по доверенной внутренней сети и корректно формировать схему запроса согласно принятой инфраструктурной конфигурации.

## Запуск и обновление

```bash
docker compose config --quiet
docker compose build
docker compose up -d
docker compose ps
docker compose logs --tail=200 web scheduler
```

`web` сначала применяет миграции, затем запускает Gunicorn. `scheduler` начинает работу только после healthy-состояния `web` и раз в минуту вызывает `manage.py run_tasks`. Проверка доступности: `GET /healthz` (HTTP 200 либо HTTPS redirect до TLS-терминатора).

Для обновления сначала создайте резервную копию, затем:

```bash
git pull --ff-only
docker compose build
docker compose up -d
docker compose ps
```

Откат приложения выполняется развёртыванием предыдущего проверенного image/tag. Откат миграций допускается только после проверки обратимости конкретной миграции и наличия свежей резервной копии.

## Резервное копирование

Согласованной единицей копии являются дамп PostgreSQL и архивы именованных volumes `media` и `exchange`, снятые в одном окне обслуживания. Пример дампа БД в custom-формате:

```bash
mkdir -p ./backups
docker compose exec -T db pg_dump -U ejournal -d ejournal -Fc > ./backups/ejournal.dump
docker run --rm -v ofoms-log-partial_media:/data -v "$PWD/backups:/backup" alpine tar -C /data -czf /backup/media.tar.gz .
docker run --rm -v ofoms-log-partial_exchange:/data -v "$PWD/backups:/backup" alpine tar -C /data -czf /backup/exchange.tar.gz .
sha256sum ./backups/ejournal.dump ./backups/media.tar.gz ./backups/exchange.tar.gz > ./backups/SHA256SUMS
```

Имя volume уточняйте через `docker compose config --volumes`. Копии шифруются, размещаются вне application host и проверяются пробным восстановлением. Рекомендуемый минимум: ежедневная копия, хранение 30 дней; окончательные RPO/RTO и срок хранения утверждает заказчик.

## Восстановление

Восстановление уничтожает текущее содержимое целевой БД, поэтому выполняется только в объявленное окно и после контрольной копии текущего состояния.

```bash
sha256sum -c ./backups/SHA256SUMS
docker compose stop web scheduler
docker compose exec -T db dropdb -U ejournal --if-exists ejournal
docker compose exec -T db createdb -U ejournal -O ejournal ejournal
docker compose exec -T db pg_restore -U ejournal -d ejournal --clean --if-exists < ./backups/ejournal.dump
docker run --rm -v ofoms-log-partial_media:/data -v "$PWD/backups:/backup" alpine sh -c 'rm -rf /data/* && tar -C /data -xzf /backup/media.tar.gz'
docker run --rm -v ofoms-log-partial_exchange:/data -v "$PWD/backups:/backup" alpine sh -c 'rm -rf /data/* && tar -C /data -xzf /backup/exchange.tar.gz'
docker compose up -d
```

После восстановления проверьте `/healthz`, вход, открытие обращения и защищённое скачивание вложения, затем зафиксируйте результат и время восстановления.

## Мониторинг и диагностика

- `docker compose ps`: `db` и `web` должны быть healthy, `scheduler` — running;
- `docker compose logs web`: HTTP/WSGI ошибки и миграции;
- `docker compose logs scheduler`: результаты автоматизированных заданий;
- модуль «События»: действия пользователей и результаты операций;
- модуль «Задачи»: последний результат и лог каждого задания.

Зависший запуск старше `TASK_STALE_AFTER_SECONDS` автоматически закрывается как ошибочный. Ручная диагностика без запуска новых заданий: `docker compose exec web .venv/bin/python manage.py run_tasks --recover-only`.

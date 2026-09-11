# Установка и промышленная эксплуатация

## Предварительные условия

- Linux-хост с Docker Engine и Docker Compose v2;
- PostgreSQL 14+ при внешнем размещении либо штатный PostgreSQL 16 из Compose;
- TLS-терминатор перед портом приложения;
- отдельные случайные значения `SECRET_KEY` и `JWT_SECRET` длиной не менее 50 символов;
- случайный пароль `DB_PASSWORD` длиной не менее 16 символов, отличный от имени БД и пользователя.

Production использует встроенный Django/psycopg pool. По умолчанию каждый процесс держит 1–4 соединения, ожидает свободное соединение и первичное подключение не более 3 секунд, а перед выдачей проверяет его здоровье. Для трёх Gunicorn workers и одного scheduler верхняя граница по умолчанию — 16 соединений. Параметры `DB_POOL_MIN_SIZE`, `DB_POOL_MAX_SIZE`, `DB_POOL_TIMEOUT` и `DB_CONNECT_TIMEOUT` меняются только с учётом `max_connections` PostgreSQL; некорректные и несогласованные значения останавливают startup.

Скопируйте `.env.example` в `.env`, замените все значения `change-me` и укажите публичные имена в `ALLOWED_HOSTS` без схемы и пути, например `journal.example.ru,admin.internal.example.ru`. Пустой список, `*`, URL и значения с пробелами запрещены. Без безопасных `SECRET_KEY`, `JWT_SECRET` и `DB_PASSWORD` production settings и Compose завершаются с ошибкой до запуска сервисов. Production defaults включают secure cookies, HTTPS redirect и HSTS. Web-сессия завершается при закрытии браузера и после восьми часов бездействия; каждый запрос сдвигает срок, а `SESSION_COOKIE_AGE` позволяет задать от 300 до 43200 секунд. Булевы security-переменные принимают только `true/false`, `1/0` или `yes/no`; опечатка останавливает startup вместо неявного отключения защиты. HSTS допускает 0–63072000 секунд.

Штатная схема предполагает TLS-терминатор перед Gunicorn. Он обязан **перезаписывать** `X-Forwarded-Proto` значением `https` и `X-Forwarded-For` одним IP-адресом исходного клиента, а не дописывать значения к входящим заголовкам. Django доверяет им при `TRUST_PROXY_SSL_HEADER=True` и `TRUST_PROXY_CLIENT_IP_HEADER=True`; второй заголовок используется обязательным журналом событий. Цепочка адресов и синтаксически неверный IP игнорируются с fallback на сетевой адрес proxy. Отключать настройки следует только при завершении TLS самим application server либо отсутствии доверенной передачи client IP. Compose по умолчанию публикует Gunicorn лишь на `127.0.0.1:8000`, чтобы внешний клиент не мог обойти proxy и подделать доверенные заголовки. Для proxy на отдельном хосте `WEB_BIND_ADDRESS` можно заменить адресом изолированного внутреннего интерфейса; открывать порт в недоверенную сеть нельзя.

Все динамические ответы портала, включая redirects, ошибки, отчёты и защищённые файлы, имеют `Cache-Control: no-store, no-cache, max-age=0, private`. Reverse proxy не должен переопределять этот заголовок или кешировать такие ответы; долгосрочное кеширование разрешено только для fingerprinted static assets WhiteNoise.

### Контракт временного входа

Доверенная подсистема передаёт JWT только методом `POST` в поле `token` либо заголовке `Authorization: Bearer`. Токен подписывается настроенным алгоритмом и отдельным `JWT_SECRET`, предназначается аудитории `JWT_AUDIENCE` и обязан содержать `sub`, `aud`, `jti`, `iat`, `exp`. Значение `sub` — GUID сотрудника единого репозитория, `jti` — новый UUID для каждого выпуска. Один токен обменивается на web-сессию только один раз: повторный запрос, в том числе из другого браузера, получает HTTP 403. Старые токены без `jti` необходимо перевыпустить.

Server-to-server клиент без browser metadata продолжает использовать Bearer или form POST напрямую. Браузерная форма обязана приходить с того же origin. Если отдельная доверенная SSO-подсистема выполняет cross-origin browser POST, перечислите её точные HTTPS origins в `TOKEN_LOGIN_TRUSTED_ORIGINS`; HTTP, credentials, path/query/fragment запрещены. Cross-site запрос от любого иного origin отклоняется до потребления `jti`, поэтому он не может подменить сессию сотрудника или погасить валидный токен.

Интерактивная auth-поверхность ограничена `/accounts/login/` и POST `/accounts/logout/`; интеграционный вход расположен на `/accounts/token-login/`. Стандартные Django password-reset/change endpoints намеренно не опубликованы: почтовое восстановление не настроено, смена, сброс и разблокировка корпоративной учётной записи выполняются администратором ТФОМС с аудитом через модуль пользователей.

## Запуск и обновление

```bash
docker compose config --quiet
docker compose build
docker compose up -d
docker compose ps
docker compose logs --tail=200 web scheduler
```

`web` сначала применяет миграции, затем через `exec` запускает Gunicorn, чтобы SIGTERM дошёл непосредственно до master-процесса. `scheduler` начинает работу только после ready-состояния `web` и через команду `run_scheduler` раз в минуту вызывает `run_tasks`; SIGTERM/SIGINT останавливает его после текущего цикла. Для db, web и scheduler действует `restart: unless-stopped`, а web/scheduler получают 75 секунд на штатное завершение. `GET /healthz` проверяет только живой HTTP-процесс, а `GET /readyz` выполняет `SELECT 1` в основной БД и возвращает 503 при потере соединения. Compose обращается к readiness с внутренним доверенным `X-Forwarded-Proto: https` и принимает только HTTP 200, поэтому HTTPS redirect не может дать ложный healthy.

Перед `web` Compose запускает одноразовый `volume-init`: он назначает рабочим каталогам `media` и `exchange` UID/GID 10001 и завершается. Gunicorn и scheduler постоянно работают без root-прав, без Linux capabilities и возможности повышения привилегий; root filesystem доступна только для чтения. Запись разрешена в именованные volumes `media`/`exchange` и ограниченный 256-МБ `tmpfs` `/tmp`. Размер временного тома оставляет запас над продуктовым лимитом обучающего видео 200 МБ; уменьшать его ниже этого значения нельзя. Первый Django upload handler отклоняет multipart `Content-Length` свыше 201 МБ до разбора и немедленно останавливает chunked-файл после 200 МБ, не дочитывая остаток; ответ HTTP 413 формируется до прикладного view. В одном запросе допускается только один файл. Reverse proxy должен устанавливать совместимый или более строгий request-body limit. Если внешний bind mount не допускает `chown`, запуск останавливается до исправления прав на host вместо старта приложения без доступа к файлам.

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
- `curl -fsS https://<host>/healthz` проверяет liveness, `curl -fsS https://<host>/readyz` — готовность приложения и PostgreSQL;
- `docker compose logs web`: HTTP/WSGI ошибки и миграции;
- `docker compose logs scheduler`: результаты автоматизированных заданий;
- модуль «События»: действия пользователей и результаты операций;
- модуль «Задачи»: последний результат и лог каждого задания.

Compose использует `json-file` с ротацией: пять файлов по 10 МБ на сервис и сжатие архивных сегментов. Для четырёх сервисов локальный верхний предел несжатых container logs составляет около 200 МБ. Централизованный сбор при необходимости настраивается на уровне Docker host; отключать локальную ротацию при этом не следует. Проверка текущего расхода: `docker system df -v` и `docker inspect --format '{{.LogPath}}' <container>`.

Зависший запуск старше `TASK_STALE_AFTER_SECONDS` автоматически закрывается как ошибочный. Ручная диагностика без запуска новых заданий: `docker compose exec web .venv/bin/python manage.py run_tasks --recover-only`.

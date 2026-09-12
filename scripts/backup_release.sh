#!/bin/sh
set -eu
umask 077

backup_root=${1:?Usage: backup_release.sh BACKUP_ROOT}
db_user=${DB_USER:-ejournal}
db_name=${DB_NAME:-ejournal}
timestamp=$(date -u +%Y%m%dT%H%M%SZ)
backup_dir=$backup_root/$timestamp
writers_stopped=0
web_container=$(docker compose ps -q -a web)
scheduler_container=$(docker compose ps -q -a scheduler)
test -n "$web_container"
test -n "$scheduler_container"
web_image=$(docker inspect --format '{{.Image}}' "$web_container")
revision=$(docker image inspect \
  --format '{{ index .Config.Labels "org.opencontainers.image.revision" }}' \
  "$web_image")
case "$revision" in
  *[!0-9a-f]*|'')
    echo >&2 "Web image has no valid Git revision label"
    exit 1
    ;;
esac
if [ "${#revision}" -ne 40 ]; then
  echo >&2 "Web image revision must be a full 40-character Git SHA"
  exit 1
fi

cleanup() {
  status=$?
  trap - EXIT HUP INT TERM
  if [ "$writers_stopped" -eq 1 ]; then
    docker start "$web_container" "$scheduler_container" >/dev/null
  fi
  exit "$status"
}
trap cleanup EXIT HUP INT TERM

mkdir -p "$backup_root"
mkdir "$backup_dir"

docker compose stop web scheduler
writers_stopped=1

docker compose exec -T db pg_dump -U "$db_user" -d "$db_name" -Fc \
  > "$backup_dir/database.dump"
docker compose run --rm --no-deps --entrypoint tar web \
  -C /app/media -czf - . > "$backup_dir/media.tar.gz"
docker compose run --rm --no-deps --entrypoint tar web \
  -C /app/exchange -czf - . > "$backup_dir/exchange.tar.gz"
db_server_version=$(docker compose exec -T db \
  psql -U "$db_user" -d "$db_name" -Atqc 'SHOW server_version')

{
  printf 'BACKUP_FORMAT_VERSION=1\n'
  printf 'CREATED_AT=%s\n' "$timestamp"
  printf 'VCS_REF=%s\n' "$revision"
  printf 'DB_NAME=%s\n' "$db_name"
  printf 'DB_SERVER_VERSION=%s\n' "$db_server_version"
} > "$backup_dir/MANIFEST"

(
  cd "$backup_dir"
  sha256sum MANIFEST database.dump media.tar.gz exchange.tar.gz > SHA256SUMS
)

docker start "$web_container" "$scheduler_container" >/dev/null
writers_stopped=0
printf 'Backup created: %s\n' "$backup_dir"

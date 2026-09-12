#!/bin/sh
set -eu
umask 077

backup_root=${1:?Usage: backup_release.sh BACKUP_ROOT}
db_user=${DB_USER:-ejournal}
db_name=${DB_NAME:-ejournal}
timestamp=$(date -u +%Y%m%dT%H%M%SZ)
backup_dir=$backup_root/$timestamp
writers_stopped=0
web_container=$(docker compose ps -q web)
scheduler_container=$(docker compose ps -q scheduler)
test -n "$web_container"
test -n "$scheduler_container"

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

(
  cd "$backup_dir"
  sha256sum database.dump media.tar.gz exchange.tar.gz > SHA256SUMS
)

docker start "$web_container" "$scheduler_container" >/dev/null
writers_stopped=0
printf 'Backup created: %s\n' "$backup_dir"

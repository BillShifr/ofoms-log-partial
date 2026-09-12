#!/bin/sh
set -eu

backup_dir=${1:?Usage: RESTORE_CONFIRM=replace-current-state restore_release.sh BACKUP_DIR}
db_user=${DB_USER:-ejournal}
db_name=${DB_NAME:-ejournal}

if [ "${RESTORE_CONFIRM:-}" != "replace-current-state" ]; then
  echo >&2 "Set RESTORE_CONFIRM=replace-current-state to allow destructive restore"
  exit 1
fi

for artifact in SHA256SUMS database.dump media.tar.gz exchange.tar.gz; do
  test -f "$backup_dir/$artifact" || {
    echo >&2 "Missing backup artifact: $artifact"
    exit 1
  }
done
(
  cd "$backup_dir"
  sha256sum -c SHA256SUMS
)
tar -tzf "$backup_dir/media.tar.gz" >/dev/null
tar -tzf "$backup_dir/exchange.tar.gz" >/dev/null

docker compose stop web scheduler
docker compose exec -T db dropdb -U "$db_user" --if-exists --force "$db_name"
docker compose exec -T db createdb -U "$db_user" -O "$db_user" "$db_name"
docker compose exec -T db pg_restore -U "$db_user" -d "$db_name" \
  < "$backup_dir/database.dump"

docker compose run --rm --no-deps --entrypoint sh web -c \
  'find /app/media -mindepth 1 -delete && tar -C /app/media -xzf -' \
  < "$backup_dir/media.tar.gz"
docker compose run --rm --no-deps --entrypoint sh web -c \
  'find /app/exchange -mindepth 1 -delete && tar -C /app/exchange -xzf -' \
  < "$backup_dir/exchange.tar.gz"

docker compose run --rm --no-deps migrate
docker compose up -d --no-deps --no-build web scheduler
printf 'Restore completed from: %s\n' "$backup_dir"

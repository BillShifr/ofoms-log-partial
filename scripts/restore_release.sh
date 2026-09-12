#!/bin/sh
set -eu

backup_dir=${1:?Usage: RESTORE_CONFIRM=replace-current-state restore_release.sh BACKUP_DIR}
db_user=${DB_USER:-ejournal}
db_name=${DB_NAME:-ejournal}

if [ "${RESTORE_CONFIRM:-}" != "replace-current-state" ]; then
  echo >&2 "Set RESTORE_CONFIRM=replace-current-state to allow destructive restore"
  exit 1
fi

for artifact in SHA256SUMS MANIFEST database.dump media.tar.gz exchange.tar.gz; do
  test -f "$backup_dir/$artifact" || {
    echo >&2 "Missing backup artifact: $artifact"
    exit 1
  }
done

manifest_value() {
  key=$1
  value=$(sed -n "s/^${key}=//p" "$backup_dir/MANIFEST")
  lines=$(printf '%s\n' "$value" | wc -l | tr -d ' ')
  if [ -z "$value" ] || [ "$lines" -ne 1 ]; then
    echo >&2 "Invalid or missing manifest field: $key"
    exit 1
  fi
  printf '%s\n' "$value"
}

format_version=$(manifest_value BACKUP_FORMAT_VERSION)
backup_revision=$(manifest_value VCS_REF)
manifest_db_name=$(manifest_value DB_NAME)
if [ "$format_version" != "1" ]; then
  echo >&2 "Unsupported backup format version: $format_version"
  exit 1
fi
case "$backup_revision" in
  *[!0-9a-f]*|'')
    echo >&2 "Backup manifest has no valid Git revision"
    exit 1
    ;;
esac
if [ "${#backup_revision}" -ne 40 ]; then
  echo >&2 "Backup revision must be a full 40-character Git SHA"
  exit 1
fi
if [ "$manifest_db_name" != "$db_name" ]; then
  echo >&2 "Backup database name does not match target DB_NAME"
  exit 1
fi

checksum_names=$(awk '{print $2}' "$backup_dir/SHA256SUMS")
if [ "$checksum_names" != "MANIFEST
database.dump
media.tar.gz
exchange.tar.gz" ]; then
  echo >&2 "SHA256SUMS must contain only the expected backup artifacts"
  exit 1
fi
(
  cd "$backup_dir"
  sha256sum -c SHA256SUMS
)
tar -tzf "$backup_dir/media.tar.gz" >/dev/null
tar -tzf "$backup_dir/exchange.tar.gz" >/dev/null
docker compose exec -T db pg_restore --list \
  < "$backup_dir/database.dump" >/dev/null

web_container=$(docker compose ps -q -a web)
test -n "$web_container"
web_image=$(docker inspect --format '{{.Image}}' "$web_container")
current_revision=$(docker image inspect \
  --format '{{ index .Config.Labels "org.opencontainers.image.revision" }}' \
  "$web_image")
if [ "$current_revision" != "$backup_revision" ]; then
  echo >&2 "Backup revision $backup_revision does not match web image revision $current_revision"
  exit 1
fi

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

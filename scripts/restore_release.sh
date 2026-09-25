#!/bin/sh
set -eu

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
. "$script_dir/lib/container_engine.sh"

backup_dir=${1:?Usage: RESTORE_CONFIRM=replace-current-state restore_release.sh BACKUP_DIR}
db_user=${DB_USER:?DB_USER is required}
db_name=${DB_NAME:?DB_NAME is required}
lock_file=${BACKUP_RESTORE_LOCK_FILE:-/tmp/ofoms-ejournal-backup-restore.lock}

if [ "${RESTORE_CONFIRM:-}" != "replace-current-state" ]; then
  echo >&2 "Set RESTORE_CONFIRM=replace-current-state to allow destructive restore"
  exit 1
fi

command -v flock >/dev/null 2>&1 || {
  echo >&2 "flock is required for backup/restore serialization"
  exit 1
}
exec 9>"$lock_file"
flock -n 9 || {
  echo >&2 "Another backup or restore operation is already running"
  exit 1
}

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
compose --profile ops run --rm --no-deps -T db-tools pg_restore --list \
  < "$backup_dir/database.dump" >/dev/null

web_container=$(compose ps -q -a web)
test -n "$web_container"
web_image=$(container_engine inspect --format '{{.Image}}' "$web_container")
current_revision=$(container_engine image inspect \
  --format '{{ index .Config.Labels "org.opencontainers.image.revision" }}' \
  "$web_image")
if [ "$current_revision" != "$backup_revision" ]; then
  echo >&2 "Backup revision $backup_revision does not match web image revision $current_revision"
  exit 1
fi

compose stop web scheduler
compose --profile ops run --rm --no-deps -T db-tools \
  dropdb --if-exists --force "$db_name"
compose --profile ops run --rm --no-deps -T db-tools \
  createdb -O "$db_user" "$db_name"
compose --profile ops run --rm --no-deps -T db-tools pg_restore -d "$db_name" \
  < "$backup_dir/database.dump"

compose run --rm --no-deps --entrypoint sh web -c \
  'find /app/media -mindepth 1 -delete && tar -C /app/media -xzf -' \
  < "$backup_dir/media.tar.gz"
compose run --rm --no-deps --entrypoint sh web -c \
  'find /app/exchange -mindepth 1 -delete && tar -C /app/exchange -xzf -' \
  < "$backup_dir/exchange.tar.gz"

DEPLOY_PULL=false sh "$script_dir/deploy_release.sh"
printf 'Restore completed from: %s\n' "$backup_dir"

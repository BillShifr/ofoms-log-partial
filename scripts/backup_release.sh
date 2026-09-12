#!/bin/sh
set -eu
umask 077

backup_root=${1:?Usage: backup_release.sh BACKUP_ROOT}
db_user=${DB_USER:-ejournal}
db_name=${DB_NAME:-ejournal}
lock_file=${BACKUP_RESTORE_LOCK_FILE:-/tmp/ofoms-ejournal-backup-restore.lock}
timestamp=$(date -u +%Y%m%dT%H%M%SZ)
backup_dir=$backup_root/$timestamp
staging_dir=$backup_dir.partial.$$
writers_stopped=0
backup_staged=0

command -v flock >/dev/null 2>&1 || {
  echo >&2 "flock is required for backup/restore serialization"
  exit 1
}
exec 9>"$lock_file"
flock -n 9 || {
  echo >&2 "Another backup or restore operation is already running"
  exit 1
}

web_container=$(docker compose ps -q -a web)
scheduler_container=$(docker compose ps -q -a scheduler)
test -n "$web_container"
test -n "$scheduler_container"
for container in "$web_container" "$scheduler_container"; do
  if [ "$(docker inspect --format '{{.State.Running}}' "$container")" != "true" ]; then
    echo >&2 "Backup requires both web and scheduler to be running"
    exit 1
  fi
done
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
    if ! docker start "$web_container" "$scheduler_container" >/dev/null; then
      echo >&2 "Failed to restart application writers"
      status=1
    fi
  fi
  if [ "$backup_staged" -eq 1 ] && [ -e "$staging_dir" ]; then
    case "$staging_dir" in
      "$backup_root"/*.partial.*)
        if ! rm -rf -- "$staging_dir"; then
          echo >&2 "Failed to remove backup staging directory: $staging_dir"
          status=1
        fi
        ;;
      *)
        echo >&2 "Refusing to remove unexpected staging path: $staging_dir"
        status=1
        ;;
    esac
  fi
  exit "$status"
}
trap cleanup EXIT HUP INT TERM

mkdir -p "$backup_root"
test ! -e "$backup_dir" || {
  echo >&2 "Backup destination already exists: $backup_dir"
  exit 1
}
mkdir "$staging_dir"
backup_staged=1

writers_stopped=1
docker compose stop web scheduler

docker compose exec -T db pg_dump -U "$db_user" -d "$db_name" -Fc \
  > "$staging_dir/database.dump"
docker compose run --rm --no-deps --entrypoint tar web \
  -C /app/media -czf - . > "$staging_dir/media.tar.gz"
docker compose run --rm --no-deps --entrypoint tar web \
  -C /app/exchange -czf - . > "$staging_dir/exchange.tar.gz"
db_server_version=$(docker compose exec -T db \
  psql -U "$db_user" -d "$db_name" -Atqc 'SHOW server_version')

{
  printf 'BACKUP_FORMAT_VERSION=1\n'
  printf 'CREATED_AT=%s\n' "$timestamp"
  printf 'VCS_REF=%s\n' "$revision"
  printf 'DB_NAME=%s\n' "$db_name"
  printf 'DB_SERVER_VERSION=%s\n' "$db_server_version"
} > "$staging_dir/MANIFEST"

(
  cd "$staging_dir"
  sha256sum MANIFEST database.dump media.tar.gz exchange.tar.gz > SHA256SUMS
)

mv "$staging_dir" "$backup_dir"
backup_staged=0

docker start "$web_container" "$scheduler_container" >/dev/null
writers_stopped=0
printf 'Backup created: %s\n' "$backup_dir"

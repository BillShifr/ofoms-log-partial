#!/bin/sh
set -eu

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
bundle_dir=$(CDPATH= cd -- "$script_dir/.." && pwd)
if [ -f "$bundle_dir/SHA256SUMS" ]; then
  (cd "$bundle_dir" && sha256sum -c SHA256SUMS)
fi
. "$script_dir/lib/container_engine.sh"

# Compose reads .env itself, but a direct Podman pull does not. Export the
# dedicated auth file so manual deployments and the systemd unit use the same
# registry credentials without copying them into the deployment bundle.
if [ -z "${REGISTRY_AUTH_FILE:-}" ] && [ -f "$bundle_dir/.env" ]; then
  REGISTRY_AUTH_FILE=$(sed -n 's/^REGISTRY_AUTH_FILE=//p' "$bundle_dir/.env")
  export REGISTRY_AUTH_FILE
fi
if [ "$CONTAINER_ENGINE" = podman ] && [ -n "${REGISTRY_AUTH_FILE:-}" ]; then
  case "$REGISTRY_AUTH_FILE" in
    /*) ;;
    *) echo >&2 "REGISTRY_AUTH_FILE must be absolute"; exit 1 ;;
  esac
  test -r "$REGISTRY_AUTH_FILE" || {
    echo >&2 "REGISTRY_AUTH_FILE is not readable: $REGISTRY_AUTH_FILE"
    exit 1
  }
fi

if [ -f "$bundle_dir/RELEASE" ]; then
  bundle_revision=$(sed -n 's/^VCS_REF=//p' "$bundle_dir/RELEASE")
  if [ -n "${VCS_REF:-}" ] && [ "$VCS_REF" != "$bundle_revision" ]; then
    echo >&2 "VCS_REF does not match the deployment bundle"
    exit 1
  fi
  VCS_REF=$bundle_revision
  export VCS_REF
fi
expected_revision=${VCS_REF:?VCS_REF must be the full Git commit SHA}
image_name="docker.io/frozendevs/tfoms-ejournal:$expected_revision"
pull_release=${DEPLOY_PULL:-true}

case "$pull_release" in true|false) ;; *) echo >&2 "DEPLOY_PULL must be true or false"; exit 1 ;; esac

compose config >/dev/null
if [ "$pull_release" = true ]; then
  container_engine pull "$image_name"
  container_engine pull \
    "docker.io/library/postgres:17-alpine@sha256:b0f9560a2de083e2cc7382e75f808c7381a32852a7ec49117deedb300e552b24"
fi
sh "$script_dir/verify_release_image.sh"

legacy_upgrade=${ALLOW_LEGACY_INPLACE_UPGRADE:-}
if [ -z "$legacy_upgrade" ] && [ -f "$bundle_dir/.env" ]; then
  legacy_upgrade=$(sed -n 's/^ALLOW_LEGACY_INPLACE_UPGRADE=//p' "$bundle_dir/.env")
fi
if [ "$legacy_upgrade" = true ]; then
  backup_file=${LEGACY_UPGRADE_BACKUP_FILE:-}
  if [ -z "$backup_file" ] && [ -f "$bundle_dir/.env" ]; then
    backup_file=$(sed -n 's/^LEGACY_UPGRADE_BACKUP_FILE=//p' "$bundle_dir/.env")
  fi
  test -n "$backup_file" || {
    echo >&2 "LEGACY_UPGRADE_BACKUP_FILE is required for the first legacy upgrade"
    exit 1
  }
  case "$backup_file" in
    /*) ;;
    *) echo >&2 "LEGACY_UPGRADE_BACKUP_FILE must be absolute"; exit 1 ;;
  esac
  test -s "$backup_file" || { echo >&2 "Legacy backup is missing or empty"; exit 1; }
  compose --profile ops run --rm --no-deps -T db-tools pg_restore --list \
    < "$backup_file" >/dev/null
fi

# Do not rely on podman-compose depends_on ordering. Stop every writer and run
# each deployment phase explicitly, checking its exit status before continuing.
compose stop web scheduler >/dev/null 2>&1 || true
compose run --rm --no-deps volume-init
compose run --rm --no-deps migrate
compose up -d --no-deps --no-build web

web_container=$(compose ps -q web)
test -n "$web_container"
attempt=0
while [ "$attempt" -lt 18 ]; do
  health=$(container_engine inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{end}}' "$web_container")
  case "$health" in
    healthy) break ;;
    unhealthy)
      compose logs --tail=200 web >&2 || true
      echo >&2 "Web container became unhealthy"
      exit 1
      ;;
  esac
  attempt=$((attempt + 1))
  sleep 5
done
if [ "$health" != healthy ]; then
  compose logs --tail=200 web >&2 || true
  echo >&2 "Web readiness timeout"
  exit 1
fi

compose up -d --no-deps --no-build scheduler
compose ps
printf 'Release deployed: %s via %s\n' "$image_name" "$CONTAINER_ENGINE"

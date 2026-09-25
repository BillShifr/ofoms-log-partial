#!/bin/sh

# общий адаптер docker и podman
if [ -z "${CONTAINER_ENGINE:-}" ]; then
  if command -v podman >/dev/null 2>&1; then
    CONTAINER_ENGINE=podman
  elif command -v docker >/dev/null 2>&1; then
    CONTAINER_ENGINE=docker
  else
    echo >&2 "Neither podman nor docker is available"
    exit 1
  fi
fi

case "$CONTAINER_ENGINE" in
  podman|docker) ;;
  *)
    echo >&2 "CONTAINER_ENGINE must be podman or docker"
    exit 1
    ;;
esac

command -v "$CONTAINER_ENGINE" >/dev/null 2>&1 || {
  echo >&2 "$CONTAINER_ENGINE is not available"
  exit 1
}

container_engine() {
  "$CONTAINER_ENGINE" "$@"
}

compose() {
  "$CONTAINER_ENGINE" compose "$@"
}

compose version >/dev/null

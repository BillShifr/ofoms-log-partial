#!/bin/sh
set -eu

image_name=${1:?Usage: container_runtime_gate.sh IMAGE}
expected_revision=${2:?Usage: container_runtime_gate.sh IMAGE EXPECTED_REVISION}

actual_revision=$(docker image inspect \
  --format '{{ index .Config.Labels "org.opencontainers.image.revision" }}' \
  "$image_name")
test "$actual_revision" = "$expected_revision"

docker run --rm \
  --network none \
  --read-only \
  --tmpfs /tmp:size=256m,mode=1777 \
  --cap-drop ALL \
  --security-opt no-new-privileges \
  "$image_name" \
  sh -c '
    ! command -v uv
    test ! -e /usr/local/bin/uv
    test ! -e /app/.pytest_cache
    test ! -e /app/.ruff_cache
    test ! -e /app/.mypy_cache
    test ! -e /app/tests
    test -z "$(find /app/apps \( -name 'tests.py' -o -name 'test_*.py' \) -print -quit)"
    test ! -e /app/scripts
    test ! -e /app/package.json
    test ! -e /app/.git
    test ! -e /app/.env
    test ! -e /app/.env.example
    test -z "$(find /app -name .DS_Store -print -quit)"
    test -z "$(find /app/exchange -type f -print -quit)"
    size_mb=$(df -m /tmp | awk "NR==2 {print \$2}")
    test "$size_mb" -ge 256
    grep -q "^CapEff:[[:space:]]*0000000000000000$" /proc/self/status
    grep -q "^NoNewPrivs:[[:space:]]*1$" /proc/self/status
    ! touch /app/runtime-write-probe
    .venv/bin/python manage.py check --settings config.settings.base
  '

probe_dir=$(mktemp -d)
cleanup() {
  rm -f "$probe_dir/owned"
  rmdir "$probe_dir"
}
trap cleanup EXIT HUP INT TERM

docker run --rm \
  --network none \
  --user 0:0 \
  --read-only \
  --security-opt no-new-privileges \
  --cap-drop ALL \
  --cap-add CHOWN \
  --mount "type=bind,src=$probe_dir,dst=/probe" \
  "$image_name" \
  sh -c '
    touch /probe/owned
    chown 10001:10001 /probe/owned
    test "$(stat -c %u:%g /probe/owned)" = "10001:10001"
    grep -q "^CapEff:[[:space:]]*0000000000000001$" /proc/self/status
    grep -q "^NoNewPrivs:[[:space:]]*1$" /proc/self/status
    ! touch /rootfs-write-probe
  '

#!/bin/sh
set -eu

revision=${1:?Usage: package_deployment_bundle.sh REVISION OUTPUT_ARCHIVE}
archive=${2:?Usage: package_deployment_bundle.sh REVISION OUTPUT_ARCHIVE}
case "$revision" in *[!0-9a-f]*|'') exit 1 ;; esac
test "${#revision}" -eq 40

root_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
staging=$(mktemp -d)
trap 'rm -rf -- "$staging"' EXIT HUP INT TERM
bundle=$staging/ofoms-ejournal-deploy
mkdir -p "$bundle/scripts/lib" "$bundle/systemd" "$bundle/nginx"
cp "$root_dir/docker-compose.yml" "$bundle/"
sed "s/^VCS_REF=.*/VCS_REF=$revision/" \
  "$root_dir/.env.production.example" > "$bundle/.env.example"
cp "$root_dir/scripts/"*release*.sh "$bundle/scripts/"
cp "$root_dir/scripts/container_runtime_gate.sh" "$bundle/scripts/"
cp "$root_dir/scripts/lib/container_engine.sh" "$bundle/scripts/lib/"
cp "$root_dir/deploy/systemd/ofoms-ejournal.service" "$bundle/systemd/"
cp "$root_dir/deploy/nginx/ofoms-ejournal.conf" "$bundle/nginx/"
printf 'VCS_REF=%s\n' "$revision" > "$bundle/RELEASE"
find "$bundle" -type f -exec chmod 600 {} +
find "$bundle/scripts" -type f -name '*.sh' -exec chmod 700 {} +
(cd "$bundle" && find . -type f ! -name SHA256SUMS -print0 | sort -z | xargs -0 sha256sum > SHA256SUMS)
tar -C "$staging" -czf "$archive" ofoms-ejournal-deploy
printf 'Deployment bundle created: %s\n' "$archive"

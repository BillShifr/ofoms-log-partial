#!/bin/sh
set -eu

expected_revision=${VCS_REF:?VCS_REF must be the full Git commit SHA}
case "$expected_revision" in
  *[!0-9a-f]*|'')
    echo >&2 "VCS_REF must be a full 40-character lowercase Git SHA"
    exit 1
    ;;
esac
if [ "${#expected_revision}" -ne 40 ]; then
  echo >&2 "VCS_REF must be a full 40-character lowercase Git SHA"
  exit 1
fi

image_name="frozendevs/tfoms-ejournal:$expected_revision"
resolved_images=$(docker compose config --images)
application_count=$(printf '%s\n' "$resolved_images" | awk -v image="$image_name" '
  $0 == image { count += 1 }
  END { print count + 0 }
')
if [ "$application_count" -ne 4 ]; then
  echo >&2 "Compose must resolve all four application services to $image_name"
  exit 1
fi
if printf '%s\n' "$resolved_images" | awk '
  /^frozendevs\/tfoms-ejournal:/ { count += 1 }
  END { exit count == 4 ? 0 : 1 }
'; then
  :
else
  echo >&2 "Compose contains an unexpected tfoms-ejournal image reference"
  exit 1
fi

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
sh "$script_dir/container_runtime_gate.sh" "$image_name" "$expected_revision"
printf 'Verified release image %s\n' "$image_name"

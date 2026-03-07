#!/usr/bin/env bash
# Validate docker-compose with AWS profile without printing resolved config (avoids leaking secrets).
# Use this instead of raw 'docker compose config' on EC2.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$ROOT_DIR"

if [[ ! -f "docker-compose.yml" ]]; then
  echo "ERROR: docker-compose.yml not found in $ROOT_DIR" >&2
  exit 1
fi

# Validate: list services only (no env/config output)
docker compose --profile aws config --services >/dev/null
echo "OK: docker-compose --profile aws config valid"

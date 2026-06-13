#!/usr/bin/env bash
# AWS-profile docker compose wrapper for PROD deploy scripts.
# Uses sudo when secrets/runtime.env exists but is not readable (owner 10001:10001, mode 600).
# Never prints secrets or resolved compose config.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$ROOT_DIR"

export COMPOSE_PROFILES="${COMPOSE_PROFILES:-aws}"

RUNTIME_ENV="$ROOT_DIR/secrets/runtime.env"
COMPOSE=(docker compose --profile aws)

if [[ -f "$RUNTIME_ENV" ]] && ! [[ -r "$RUNTIME_ENV" ]]; then
  if ! sudo -n true 2>/dev/null && ! sudo -v 2>/dev/null; then
    echo "ERROR: secrets/runtime.env is not readable by $(whoami) (expected owner 10001:10001, mode 600)." >&2
    echo "Fix: use sudo for compose, or run: sudo chown \$(whoami):\$(whoami) secrets/runtime.env && chmod 600 secrets/runtime.env" >&2
    echo "Deploy pattern: sudo docker compose --profile aws <command>" >&2
    exit 1
  fi
  COMPOSE=(sudo docker compose --profile aws)
fi

exec "${COMPOSE[@]}" "$@"

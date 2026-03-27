#!/usr/bin/env bash
# Fail unless invoked from the canonical prod tree and AWS backend is healthy.
# backend-aws env_file (see docker-compose.yml): .env, .env.aws, secrets/runtime.env — all under this root.
set -euo pipefail

REQUIRED_ROOT="/home/ubuntu/crypto-2.0"
COMPOSE_REL="docker-compose.yml"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd -P)"

echo "check_runtime: cwd=$(pwd -P)"
echo "check_runtime: repo_root=$ROOT"

if [[ "$ROOT" != "$REQUIRED_ROOT" ]]; then
  echo "ERROR: Repository must be checked out at $REQUIRED_ROOT (resolved: $ROOT)." >&2
  exit 1
fi

PWDRES="$(pwd -P)"
case "$PWDRES" in
  "$REQUIRED_ROOT"|"$REQUIRED_ROOT"/*) ;;
  *)
    echo "ERROR: Current working directory must be inside $REQUIRED_ROOT (got: $PWDRES)." >&2
    exit 1
    ;;
esac

COMPOSE_FILE="$REQUIRED_ROOT/$COMPOSE_REL"
if [[ ! -f "$COMPOSE_FILE" ]]; then
  echo "ERROR: Missing compose file: $COMPOSE_FILE" >&2
  exit 1
fi

if ! docker compose -f "$COMPOSE_FILE" --profile aws config >/dev/null 2>&1; then
  echo "ERROR: docker compose config failed for $COMPOSE_FILE (profile aws)." >&2
  exit 1
fi

RESOLVED="$(docker compose -f "$COMPOSE_FILE" --profile aws config 2>/dev/null | head -1 || true)"
if [[ -n "$RESOLVED" ]]; then
  echo "check_runtime: compose project name line: $RESOLVED"
fi

for envf in secrets/runtime.env .env .env.aws; do
  if [[ ! -f "$REQUIRED_ROOT/$envf" ]]; then
    echo "ERROR: Missing $REQUIRED_ROOT/$envf (required by backend-aws env_file in docker-compose.yml)." >&2
    exit 1
  fi
done

if ! docker ps --filter "status=running" --format '{{.Names}}' | grep -qE '^automated-trading-platform-backend-aws-1$'; then
  echo "ERROR: Container automated-trading-platform-backend-aws-1 is not running." >&2
  exit 1
fi

WORKDIR="$(docker inspect automated-trading-platform-backend-aws-1 --format '{{index .Config.Labels "com.docker.compose.project.working_dir"}}' 2>/dev/null || true)"
CFG="$(docker inspect automated-trading-platform-backend-aws-1 --format '{{index .Config.Labels "com.docker.compose.project.config_files"}}' 2>/dev/null || true)"
if [[ "$WORKDIR" != "$REQUIRED_ROOT" ]]; then
  echo "ERROR: backend-aws compose working_dir label is '$WORKDIR' (expected $REQUIRED_ROOT)." >&2
  exit 1
fi
if [[ "$CFG" != "$COMPOSE_FILE" ]]; then
  echo "ERROR: backend-aws compose config_files label is '$CFG' (expected $COMPOSE_FILE)." >&2
  exit 1
fi

echo "OK: single-runtime checks passed (compose=$COMPOSE_FILE, backend-aws labels match $REQUIRED_ROOT)."

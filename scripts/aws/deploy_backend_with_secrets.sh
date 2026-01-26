#!/usr/bin/env bash
set -euo pipefail
set +x 2>/dev/null || true

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$SCRIPT_DIR/../.."
ROOT_DIR="$(cd "$ROOT_DIR" && pwd)"

if [[ ! -f "$ROOT_DIR/docker-compose.yml" ]]; then
  SEARCH_DIR="$SCRIPT_DIR"
  while [[ "$SEARCH_DIR" != "/" ]]; do
    if [[ -f "$SEARCH_DIR/docker-compose.yml" ]]; then
      ROOT_DIR="$SEARCH_DIR"
      break
    fi
    SEARCH_DIR="$(dirname "$SEARCH_DIR")"
  done
fi

if [[ ! -f "$ROOT_DIR/docker-compose.yml" ]]; then
  echo "ERROR: repo root not found (docker-compose.yml missing)" >&2
  exit 1
fi

cd "$ROOT_DIR"

mkdir -p secrets

echo "== RENDER RUNTIME ENV =="
bash scripts/aws/render_runtime_env.sh

if [[ ! -f "$ROOT_DIR/secrets/runtime.env" ]]; then
  echo "ERROR: secrets/runtime.env missing after render. Aborting." >&2
  exit 1
fi

echo "== SMOKE TEST (keys only, no secrets) =="
bash scripts/aws/smoke_test_runtime_env.sh "$ROOT_DIR/secrets/runtime.env"

echo "== DEPLOY BACKEND-AWS =="
BACKEND_SVC="$(docker compose --profile aws config --services 2>/dev/null | grep -E '^backend-aws$' || true)"
[[ -z "$BACKEND_SVC" ]] && BACKEND_SVC="backend-aws"
# Compose must run from repo root (env_file paths are relative).
cd "$ROOT_DIR" && docker compose --profile aws up -d --build "$BACKEND_SVC" || {
  echo "ERROR: compose failed for service $BACKEND_SVC. Check docker compose --profile aws config." >&2
  exit 1
}

echo "== WAIT FOR HEALTH =="
start_ts="$(date +%s)"
while true; do
  if curl -sS http://localhost:8002/health | grep -q '"status":"ok"'; then
    echo "Health OK"
    break
  fi
  now_ts="$(date +%s)"
  if (( now_ts - start_ts > 60 )); then
    echo "ERROR: health check did not become healthy within 60s" >&2
    curl -sS http://localhost:8002/health || true
    exit 1
  fi
  sleep 3
done

echo "== VERIFY RUNTIME =="
bash scripts/aws/verify_backend_runtime.sh

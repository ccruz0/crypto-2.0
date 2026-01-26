#!/usr/bin/env bash
# One-command AWS backend deploy: render runtime.env, deploy backend-aws, print evidence (no secrets).
# Always run this instead of `docker compose --profile aws up -d backend-aws` directly.
# Usage: cd /home/ubuntu/automated-trading-platform && bash scripts/aws/aws_up_backend.sh
set -euo pipefail
set +x 2>/dev/null || true

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="${AWS_REPO_ROOT:-}"
if [[ -z "$ROOT_DIR" || ! -f "$ROOT_DIR/docker-compose.yml" ]]; then
  ROOT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
  while [[ "$ROOT_DIR" != "/" ]]; do
    [[ -f "$ROOT_DIR/docker-compose.yml" ]] && break
    ROOT_DIR="$(dirname "$ROOT_DIR")"
  done
fi
if [[ ! -f "$ROOT_DIR/docker-compose.yml" ]]; then
  echo "ERROR: repo root not found (docker-compose.yml missing)" >&2
  exit 1
fi

cd "$ROOT_DIR"

echo "== DEPLOY (render -> smoke -> compose -> health -> verify) =="
bash scripts/aws/deploy_backend_with_secrets.sh

echo ""
echo "== EVIDENCE (no secrets) =="
RUNTIME="$ROOT_DIR/secrets/runtime.env"
if [[ -f "$RUNTIME" ]]; then
  echo "runtime.env presence=YES"
  # Key names only; never print values.
  keys_line="$(grep -oE '^[A-Z_]+' "$RUNTIME" | tr '\n' ' ')"
  echo "keys=${keys_line}"
else
  echo "runtime.env presence=NO"
fi
echo -n "health: "
curl -sS http://localhost:8002/health 2>/dev/null | head -c 100 || echo "(request failed)"
echo

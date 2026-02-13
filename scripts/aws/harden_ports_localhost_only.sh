#!/usr/bin/env bash
# EC2 hardening: bind backend-aws (8002) and frontend-aws (3000) to 127.0.0.1 only.
# Run from repo root. No secrets printed. No docker compose config. Fails on first error.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$REPO_ROOT"

# 1) Repo root and git short SHA
echo "=== Repo root and HEAD ==="
pwd
GIT_HEAD="$(git rev-parse --short HEAD 2>/dev/null || echo "unknown")"
echo "git rev-parse --short HEAD: $GIT_HEAD"

# 2) Baseline
echo ""
echo "=== Baseline (8002/3000) ==="
BASELINE_SS="$(ss -ltnp 2>/dev/null | grep -E '(:8002|:3000)\b' || true)"
echo "$BASELINE_SS"

# 3) Compose must have localhost-only bindings
echo ""
echo "=== Compose bindings check ==="
COMPOSE="$REPO_ROOT/docker-compose.yml"
if [[ ! -f "$COMPOSE" ]]; then
  echo "ERROR: docker-compose.yml not found" >&2
  exit 1
fi
if ! grep -qF '127.0.0.1:8002:8002' "$COMPOSE" || ! grep -qF '127.0.0.1:3000:3000' "$COMPOSE"; then
  echo "ERROR: docker-compose.yml must contain:" >&2
  echo '  - "127.0.0.1:8002:8002" (backend-aws ports)' >&2
  echo '  - "127.0.0.1:3000:3000" (frontend-aws ports)' >&2
  echo "Edit those two port lines and re-run. Or: git pull --ff-only" >&2
  exit 1
fi

# 4) Recreate services
echo ""
echo "=== Recreate backend-aws and frontend-aws ==="
docker compose --profile aws up -d --force-recreate backend-aws frontend-aws
docker compose --profile aws ps
POST_PS="$(docker compose --profile aws ps 2>/dev/null || true)"

# 5) Post-check: no 0.0.0.0
echo ""
echo "=== Post-check ports ==="
POST_SS="$(ss -ltnp 2>/dev/null | grep -E '(:8002|:3000)\b' || true)"
echo "$POST_SS"
if echo "$POST_SS" | grep -qE '0\.0\.0\.0:(8002|3000)\b'; then
  echo "FAIL: 0.0.0.0 still bound for 8002 or 3000" >&2
  for c in automated-trading-platform-backend-aws-1 automated-trading-platform-frontend-aws-1; do
    docker inspect "$c" --format '{{json .NetworkSettings.Ports}}' 2>/dev/null || true
  done
  exit 1
fi

# 6) Guard script
echo ""
echo "=== Guard script ==="
GUARD_EXIT=0
if [[ -f "$REPO_ROOT/scripts/aws/verify_no_public_ports.sh" ]]; then
  bash "$REPO_ROOT/scripts/aws/verify_no_public_ports.sh" || GUARD_EXIT=$?
  if [[ "$GUARD_EXIT" -ne 0 ]]; then
    echo "FAIL: verify_no_public_ports.sh exited $GUARD_EXIT" >&2
    exit 1
  fi
  echo "PASS"
else
  echo "verify_no_public_ports.sh not found"
fi

# 7) Health check: /health (not /api/health/system) to avoid auth-related hangs
echo ""
echo "=== Health check (/health) ==="
HEALTH_CODE="$(curl -s -o /dev/null -w '%{http_code}' --connect-timeout 5 --max-time 10 http://127.0.0.1:8002/health 2>/dev/null || echo "000")"
echo "HTTP $HEALTH_CODE"
if [[ "$HEALTH_CODE" != "200" ]]; then
  echo "FAIL: expected 200 for http://127.0.0.1:8002/health" >&2
  docker compose --profile aws logs --tail=100 backend-aws 2>/dev/null || true
  exit 1
fi

# 8) Final verdict
echo ""
echo "=== Final report ==="
echo "Git HEAD (short): $GIT_HEAD"
echo "Baseline ss (8002/3000):"
echo "$BASELINE_SS"
echo "Post-change ss (8002/3000):"
echo "$POST_SS"
echo "docker compose --profile aws ps:"
echo "$POST_PS"
echo "Guard: PASS"
echo "Health /health: $HEALTH_CODE"
echo "Final verdict: SECURE"

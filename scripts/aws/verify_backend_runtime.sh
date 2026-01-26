#!/usr/bin/env bash
set -euo pipefail
set +x 2>/dev/null || true

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$SCRIPT_DIR/../.."
ROOT_DIR="$(cd "$ROOT_DIR" && pwd)"

if [[ ! -f "$ROOT_DIR/docker-compose.yml" ]]; then
  echo "ERROR: repo root not found (docker-compose.yml missing)" >&2
  exit 1
fi

CONTAINER="$(docker ps -q --filter 'name=backend-aws' | head -1)"
if [[ -z "$CONTAINER" ]]; then
  echo "ERROR: backend-aws container not running" >&2
  exit 1
fi

echo "== ENV CHECK (presence only, no values) =="
docker exec "$CONTAINER" python3 - <<'PY'
import os
def present(name):
    return "yes" if bool((os.getenv(name) or "").strip()) else "no"

keys = [
    "ENVIRONMENT",
    "RUN_TELEGRAM",
    "TELEGRAM_BOT_TOKEN",
    "TELEGRAM_CHAT_ID",
    "ADMIN_ACTIONS_KEY",
    "DIAGNOSTICS_API_KEY",
]
for key in keys:
    print(f"{key}_PRESENT={present(key)}")
PY

echo "== HEALTH =="
HEALTH_OUT="$(curl -sS -w '\n%{http_code}' http://localhost:8002/health 2>/dev/null || true)"
HTTP_CODE="$(echo "$HEALTH_OUT" | tail -1)"
if [[ "$HTTP_CODE" != "200" ]]; then
  echo "$HEALTH_OUT" | head -n -1 || true
  BIND_ERR="$(docker logs --since 5m "$CONTAINER" 2>&1 | grep -iE "bind|address already in use|already in use" | tail -5 || true)"
  if [[ -n "$BIND_ERR" ]]; then
    echo "Hint: port 8002 may be in use. Run: lsof -i :8002" >&2
  fi
else
  echo "$HEALTH_OUT" | head -n -1
fi
echo

echo "== EVALUATE SYMBOL =="
KEY="$(docker exec "$CONTAINER" sh -lc 'printf "%s" "${ADMIN_ACTIONS_KEY:-${DIAGNOSTICS_API_KEY}}"' || true)"
if [[ -z "$KEY" ]]; then
  echo "ADMIN key missing in container"
else
  curl -sS -X POST http://localhost:8002/api/admin/debug/evaluate-symbol \
    -H "Content-Type: application/json" \
    -H "X-Admin-Key: $KEY" \
    -d '{"symbol":"BTC_USDT"}'
  echo
fi

echo "== TELEGRAM LOGS (last 5m) =="
docker logs --since 5m "$CONTAINER" | tail -300 | egrep "TELEGRAM|send|SUCCESS|status" || true

echo "== DB TELEGRAM MESSAGES (last 30m) =="
docker exec "$CONTAINER" python3 - <<'PY'
import sys
from datetime import datetime, timedelta, timezone
sys.path.append("/app")
from app.database import SessionLocal
from app.models.telegram_message import TelegramMessage

db = SessionLocal()
threshold = datetime.now(timezone.utc) - timedelta(minutes=30)
rows = (
    db.query(TelegramMessage)
      .filter(TelegramMessage.timestamp >= threshold)
      .order_by(TelegramMessage.timestamp.desc())
      .limit(20)
      .all()
)
for r in rows:
    msg = (r.message or "")[:80].replace("\n", " ")
    print(r.timestamp, r.symbol, r.blocked, r.reason_code, r.throttle_status, msg)
db.close()
PY

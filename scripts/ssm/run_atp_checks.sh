#!/usr/bin/env bash
# Canonical copy: deploy to PROD as /home/ubuntu/run_atp_checks.sh (same content).
# See scripts/ssm/prod-check.sh for SSM one-shot from your laptop.
set -euo pipefail

detect_atp_dir() {
  if [[ -d /home/ubuntu/crypto-2.0 ]]; then
    printf '%s\n' /home/ubuntu/crypto-2.0
    return 0
  fi
  if [[ -d /home/ubuntu/automated-trading-platform ]]; then
    printf '%s\n' /home/ubuntu/automated-trading-platform
    return 0
  fi
  echo "ERROR: Neither /home/ubuntu/crypto-2.0 nor /home/ubuntu/automated-trading-platform exists." >&2
  echo "Contents of /home/ubuntu:" >&2
  ls -la /home/ubuntu >&2 || true
  exit 1
}

ATP_DIR="$(detect_atp_dir)"
export ATP_DIR
cd "$ATP_DIR"

echo "=== ATP CHECKS ==="
echo "==> ATP_DIR=$ATP_DIR"
echo "==> docker compose --profile aws ps"
docker compose --profile aws ps

echo "==> startup dedup log lines (up to 5 matches, optional)"
set +e
docker compose --profile aws logs backend-aws 2>&1 | { grep -F '[STARTUP_DB_CHECK] telegram_update_dedup=' || true; } | tail -5
set -e

echo "==> table_exists telegram_update_dedup"
docker compose --profile aws exec -T backend-aws python -c \
  "from app.database import engine, table_exists; print('telegram_update_dedup', table_exists(engine, 'telegram_update_dedup'))"

echo "==> PID 1 cmdline (backend-aws)"
docker compose --profile aws exec -T backend-aws sh -c 'tr "\0" " " < /proc/1/cmdline; echo'

echo "==> ATP section finished OK"

echo ""
echo "=== OPENCLAW CHECK ==="
OPENCLAW_OUT="$(
  set +e
  set +o pipefail
  set +u

  OPENCLAW_COMPOSE="/home/ubuntu/crypto-2.0/docker-compose.openclaw.yml"
  if [[ ! -f "$OPENCLAW_COMPOSE" ]]; then
    echo "OpenClaw not installed, skipping"
    exit 0
  fi

  if ! docker ps --format '{{.Names}}' 2>/dev/null | grep -q openclaw; then
    echo "OpenClaw container not running"
    exit 0
  fi

  PORT="${OPENCLAW_GATEWAY_PORT:-${OPENCLAW_HOST_PORT:-18790}}"
  CFG="/opt/openclaw/home-data/openclaw.json"
  if [[ ! -r "$CFG" ]]; then
    echo "OpenClaw FAILED"
    docker logs openclaw --tail 20 2>/dev/null || true
    exit 0
  fi

  # Graceful token read (missing keys / bad JSON → empty TOKEN).
  TOKEN="$(
    python3 -c "
import json
try:
    with open('/opt/openclaw/home-data/openclaw.json') as f:
        d = json.load(f)
    print(d.get('gateway', {}).get('auth', {}).get('token', '') or '')
except Exception:
    pass
" 2>/dev/null
  )"

  if [[ -z "$TOKEN" ]]; then
    echo "OpenClaw FAILED"
    docker logs openclaw --tail 20 2>/dev/null || true
    exit 0
  fi

  RESP="$(
    curl -sS --connect-timeout 5 --max-time 60 -w "\nhttp_code=%{http_code}" \
      -X POST "http://127.0.0.1:${PORT}/v1/responses" \
      -H "Authorization: Bearer ${TOKEN}" \
      -H "Content-Type: application/json" \
      -d '{"model":"openai/gpt-4o-mini","input":"Say only: ok"}' 2>/dev/null || true
  )"
  HTTP_LINE="$(printf '%s\n' "$RESP" | tail -n1)"
  HTTP_CODE="${HTTP_LINE#http_code=}"
  BODY="$(printf '%s\n' "$RESP" | sed '$d')"

  if [[ "$HTTP_CODE" == "200" ]] && [[ "$BODY" == *"ok"* ]]; then
    echo "OpenClaw OK"
  else
    echo "OpenClaw FAILED"
    docker logs openclaw --tail 20 2>/dev/null || true
  fi
  exit 0
)" || true
printf '%s\n' "$OPENCLAW_OUT"

if printf '%s\n' "$OPENCLAW_OUT" | grep -q '^OpenClaw FAILED$'; then
  if [[ "${OPENCLAW_HEALTH_ALERT_TELEGRAM:-}" == "true" ]]; then
    if [[ -n "${TELEGRAM_BOT_TOKEN:-}" && -n "${TELEGRAM_CHAT_ID:-}" ]]; then
      _oc_msg="⚠️ OpenClaw health check failed on $(hostname). Check docker logs openclaw --tail 20"
      curl -sS --connect-timeout 5 --max-time 15 -f -X POST \
        "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
        -d "chat_id=${TELEGRAM_CHAT_ID}" \
        --data-urlencode "text=${_oc_msg}" \
        >/dev/null 2>&1 || true
      echo "==> OpenClaw Telegram alert sent."
    else
      echo "==> OpenClaw Telegram alert skipped (missing TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID)."
    fi
  fi
fi

echo "==> run_atp_checks.sh finished OK"

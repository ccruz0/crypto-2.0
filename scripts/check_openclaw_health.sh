#!/usr/bin/env bash
# Cron-friendly OpenClaw gateway check. Optional Telegram alert on failure (secrets/runtime.env).
# Set OPENCLAW_HEALTH_ALERT_TELEGRAM=0 to skip Telegram.
# Port: OPENCLAW_GATEWAY_PORT, else OPENCLAW_HOST_PORT (same as docker-compose.openclaw.yml), else 18790.
set -euo pipefail

REPO_ROOT="${OPENCLAW_REPO_ROOT:-/home/ubuntu/crypto-2.0}"
RUNTIME_ENV="$REPO_ROOT/secrets/runtime.env"
GATEWAY_PORT="${OPENCLAW_GATEWAY_PORT:-${OPENCLAW_HOST_PORT:-18790}}"
CONFIG_JSON="/opt/openclaw/home-data/openclaw.json"

load_telegram_env() {
  [[ "${OPENCLAW_HEALTH_ALERT_TELEGRAM:-1}" == "0" ]] && return 0
  [[ -f "$RUNTIME_ENV" ]] || return 0
  set +u
  # shellcheck source=/dev/null
  source "$RUNTIME_ENV" 2>/dev/null || true
  set -u
  [[ -z "${TELEGRAM_CHAT_ID:-}" && -n "${TELEGRAM_CHAT_ID_AWS:-}" ]] && TELEGRAM_CHAT_ID="${TELEGRAM_CHAT_ID_AWS}"
  export TELEGRAM_CHAT_ID="${TELEGRAM_CHAT_ID_OPS:-${TELEGRAM_CHAT_ID:-}}"
}

notify_fail() {
  [[ "${OPENCLAW_HEALTH_ALERT_TELEGRAM:-1}" == "0" ]] && return 0
  local msg="OpenClaw health check FAILED on $(hostname -s) at $(date -u +%Y-%m-%dT%H:%M:%SZ) (port ${GATEWAY_PORT})."
  if [[ -f "$REPO_ROOT/scripts/aws/_notify_telegram_fail.sh" ]]; then
    bash "$REPO_ROOT/scripts/aws/_notify_telegram_fail.sh" "$msg" || true
  fi
}

T=$(jq -r '.gateway.auth.token // empty' "$CONFIG_JSON")
[[ -n "$T" ]] || {
  echo "❌ OpenClaw FAILED (no gateway token in $CONFIG_JSON)"
  load_telegram_env
  notify_fail
  exit 1
}

RES=$(curl -sS --connect-timeout 5 --max-time 60 \
  -X POST "http://127.0.0.1:${GATEWAY_PORT}/v1/responses" \
  -H "Authorization: Bearer $T" \
  -H "Content-Type: application/json" \
  -d '{"model":"openai/gpt-4o-mini","input":"ping"}')

if echo "$RES" | grep -q "error"; then
  echo "❌ OpenClaw FAILED"
  docker logs openclaw --tail 20
  load_telegram_env
  notify_fail
  exit 1
fi

echo "✅ OpenClaw OK"

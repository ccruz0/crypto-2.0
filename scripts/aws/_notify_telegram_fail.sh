#!/usr/bin/env bash
# Send a short failure message to Telegram. No secrets printed. Used by nightly_integrity_audit.sh.
# Usage: _notify_telegram_fail.sh "Short message"
# If TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID are unset, does nothing and returns 0.
set -euo pipefail

MSG="${1:-Nightly integrity audit failed}"
# Never echo token or full chat id
if [[ -z "${TELEGRAM_BOT_TOKEN:-}" ]] || [[ -z "${TELEGRAM_CHAT_ID:-}" ]]; then
  exit 0
fi
# POST with --data-urlencode so message is safely encoded; no token in logs
if curl -sf -o /dev/null --connect-timeout 10 --max-time 15 \
  -X POST "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
  -d "chat_id=${TELEGRAM_CHAT_ID}" \
  --data-urlencode "text=${MSG}" \
  -d "disable_web_page_preview=1" \
  2>/dev/null; then
  exit 0
fi
exit 1

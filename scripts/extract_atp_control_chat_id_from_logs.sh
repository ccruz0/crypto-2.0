#!/usr/bin/env bash
# Extract chat_id from [TG][AUTH][DENY] logs and run add_atp_control_chat_id.sh.
# Run after sending /menu from ATP Control Alerts channel.
#
# Usage: ./scripts/extract_atp_control_chat_id_from_logs.sh [backend-service]
# Default backend: backend-aws (try backend-dev for local)

set -e
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SERVICE="${1:-backend-aws}"

cd "$REPO_ROOT"
LOG=$(docker compose --profile aws logs "$SERVICE" 2>&1 | grep '\[TG\]\[AUTH\]\[DENY\]' | tail -1)
if [[ -z "$LOG" ]]; then
  # Try local profile
  LOG=$(docker compose --profile local logs backend-dev 2>&1 | grep '\[TG\]\[AUTH\]\[DENY\]' | tail -1)
fi
if [[ -z "$LOG" ]]; then
  echo "No [TG][AUTH][DENY] log found. Send /menu from ATP Control Alerts channel, then run this again." >&2
  exit 1
fi

# Extract chat_id= value (e.g. chat_id=-1001234567890)
CHAT_ID=$(echo "$LOG" | grep -oE 'chat_id=-?[0-9]+' | head -1 | cut -d= -f2)
if [[ -z "$CHAT_ID" ]]; then
  echo "Could not extract chat_id from log." >&2
  echo "Log: $LOG" >&2
  exit 1
fi

echo "Extracted chat_id=$CHAT_ID from logs. Adding to secrets/runtime.env..."
exec "$REPO_ROOT/scripts/add_atp_control_chat_id.sh" "$CHAT_ID"

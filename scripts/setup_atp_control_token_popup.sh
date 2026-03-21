#!/usr/bin/env bash
# Popup to paste ATP Control Bot Token and Chat ID, save to secrets/runtime.env.
# ATP Control (@ATP_control_bot) = tasks, approvals, investigations.
# Uses macOS AppleScript (hidden input). Linux: use zenity if available.
#
# Usage: ./scripts/setup_atp_control_token_popup.sh

set -e
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="$REPO_ROOT/secrets/runtime.env"

_get_token() {
  local prompt="$1"
  local title="$2"
  if [[ "$(uname)" == "Darwin" ]]; then
    osascript -e "
      tell application \"System Events\" to activate
      display dialog \"$prompt\" with title \"$title\" default answer \"\" with hidden answer
      return text returned of result
    " 2>/dev/null || true
  elif command -v zenity &>/dev/null; then
    zenity --password --title="$title" --text="$prompt" 2>/dev/null || true
  else
    echo "No popup available. Set TELEGRAM_ATP_CONTROL_BOT_TOKEN and TELEGRAM_ATP_CONTROL_CHAT_ID in secrets/runtime.env manually." >&2
    exit 1
  fi
}

_get_chat_id() {
  local prompt="$1"
  local title="$2"
  if [[ "$(uname)" == "Darwin" ]]; then
    osascript -e "
      tell application \"System Events\" to activate
      display dialog \"$prompt\" with title \"$title\" default answer \"\"
      return text returned of result
    " 2>/dev/null || true
  elif command -v zenity &>/dev/null; then
    zenity --entry --title="$title" --text="$prompt" 2>/dev/null || true
  else
    echo "No popup available. Set TELEGRAM_ATP_CONTROL_CHAT_ID in secrets/runtime.env manually." >&2
    exit 1
  fi
}

_upsert_env() {
  local key="$1"
  local val="$2"
  mkdir -p "$(dirname "$ENV_FILE")"
  if [[ -f "$ENV_FILE" ]]; then
    if grep -q "^[[:space:]]*${key}=" "$ENV_FILE" 2>/dev/null; then
      grep -v "^[[:space:]]*${key}=" "$ENV_FILE" > "${ENV_FILE}.tmp"
      echo "${key}=${val}" >> "${ENV_FILE}.tmp"
      mv "${ENV_FILE}.tmp" "$ENV_FILE"
    else
      echo "${key}=${val}" >> "$ENV_FILE"
    fi
  else
    echo "${key}=${val}" >> "$ENV_FILE"
  fi
}

echo "=== ATP Control Telegram Setup ==="
echo "  Bot: @ATP_control_bot (tasks, approvals, investigations)"
echo ""

TOKEN=$(_get_token "Paste your ATP Control Bot Token (from @BotFather):" "ATP Control Token")
if [[ -z "$TOKEN" ]]; then
  echo "Cancelled or empty. No change made."
  exit 0
fi
TOKEN=$(echo "$TOKEN" | sed -e 's/^[[:space:]"'\'']*//' -e 's/[[:space:]"'\'']*$//')
[[ -z "$TOKEN" ]] && { echo "Empty token. No change made."; exit 0; }

CHAT_ID=$(_get_chat_id "Paste your ATP Control Chat/Channel ID (e.g. -1001234567890):" "ATP Control Chat ID")
if [[ -z "$CHAT_ID" ]]; then
  echo "Chat ID cancelled. Saving token only."
  CHAT_ID=""
else
  CHAT_ID=$(echo "$CHAT_ID" | sed -e 's/^[[:space:]"'\'']*//' -e 's/[[:space:]"'\'']*$//')
fi

_upsert_env "TELEGRAM_ATP_CONTROL_BOT_TOKEN" "$TOKEN"
[[ -n "$CHAT_ID" ]] && _upsert_env "TELEGRAM_ATP_CONTROL_CHAT_ID" "$CHAT_ID"

echo ""
echo "Saved to secrets/runtime.env:"
echo "  TELEGRAM_ATP_CONTROL_BOT_TOKEN=***"
[[ -n "$CHAT_ID" ]] && echo "  TELEGRAM_ATP_CONTROL_CHAT_ID=$CHAT_ID"
echo ""
echo "For AWS: add these to secrets/runtime.env or SSM, then restart backend-aws."

#!/usr/bin/env bash
# Popup to paste Telegram Bot Token and save to secrets/runtime.env.
# Uses macOS AppleScript (hidden input).
# Usage: ./scripts/telegram_token_popup.sh

set -e
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="$REPO_ROOT/secrets/runtime.env"
KEY_NAME="TELEGRAM_BOT_TOKEN"

# Show dialog; hidden answer masks typing
RESPONSE=$(osascript -e '
tell application "System Events"
  activate
end tell
display dialog "Paste your Telegram Bot Token (from @BotFather):" with title "Telegram API Token" default answer "" with hidden answer
set theAnswer to text returned of result
return theAnswer
' 2>/dev/null) || true

if [[ -z "$RESPONSE" ]]; then
  echo "Cancelled or empty. No change made."
  exit 0
fi

# Trim and strip quotes
TOKEN=$(echo "$RESPONSE" | sed -e 's/^[[:space:]"'\'']*//' -e 's/[[:space:]"'\'']*$//')

if [[ -z "$TOKEN" ]]; then
  echo "Empty token. No change made."
  exit 0
fi

mkdir -p "$(dirname "$ENV_FILE")"
LINE="${KEY_NAME}=${TOKEN}"

if [[ -f "$ENV_FILE" ]]; then
  if grep -q "^[[:space:]]*${KEY_NAME}=" "$ENV_FILE" 2>/dev/null; then
    grep -v "^[[:space:]]*${KEY_NAME}=" "$ENV_FILE" > "${ENV_FILE}.tmp"
    echo "$LINE" >> "${ENV_FILE}.tmp"
    mv "${ENV_FILE}.tmp" "$ENV_FILE"
    echo "Updated TELEGRAM_BOT_TOKEN in secrets/runtime.env"
  else
    echo "$LINE" >> "$ENV_FILE"
    echo "Added TELEGRAM_BOT_TOKEN to secrets/runtime.env"
  fi
else
  echo "$LINE" >> "$ENV_FILE"
  echo "Created secrets/runtime.env with TELEGRAM_BOT_TOKEN"
fi

echo "Done. Run the diagnostic:"
echo "  cd backend && PYTHONPATH=. python scripts/diag/telegram_agent_interface_test.py"

#!/usr/bin/env bash
# Popup to paste Notion Internal Integration Secret and save to backend/.env.
# Uses macOS AppleScript (no Python tkinter needed).
# Usage: ./scripts/notion_secret_popup.sh

set -e
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="$REPO_ROOT/backend/.env"
KEY_NAME="NOTION_API_KEY"

# Show dialog; hidden answer masks typing
RESPONSE=$(osascript -e '
tell application "System Events"
  activate
end tell
display dialog "Paste your Notion Internal Integration Secret:" with title "Notion API Secret" default answer "" with hidden answer
set theAnswer to text returned of result
return theAnswer
' 2>/dev/null) || true

if [[ -z "$RESPONSE" ]]; then
  echo "Cancelled or empty. No change made."
  exit 0
fi

# Trim and strip quotes
SECRET=$(echo "$RESPONSE" | sed -e 's/^[[:space:]"'\'']*//' -e 's/[[:space:]"'\'']*$//')

if [[ -z "$SECRET" ]]; then
  echo "Empty secret. No change made."
  exit 0
fi

mkdir -p "$(dirname "$ENV_FILE")"
LINE="${KEY_NAME}=${SECRET}"

if [[ -f "$ENV_FILE" ]]; then
  if grep -q "^[[:space:]]*${KEY_NAME}=" "$ENV_FILE" 2>/dev/null; then
    # Replace existing line without putting secret in sed (avoids escaping issues)
    grep -v "^[[:space:]]*${KEY_NAME}=" "$ENV_FILE" > "${ENV_FILE}.tmp"
    echo "$LINE" >> "${ENV_FILE}.tmp"
    mv "${ENV_FILE}.tmp" "$ENV_FILE"
    echo "Updated NOTION_API_KEY in backend/.env"
  else
    echo "$LINE" >> "$ENV_FILE"
    echo "Added NOTION_API_KEY to backend/.env"
  fi
else
  echo "$LINE" >> "$ENV_FILE"
  echo "Created backend/.env with NOTION_API_KEY"
fi

echo "Done. Run: NOTION_TASK_DB=eb90cfa139f94724a8b476315908510a ./scripts/run_notion_task_pickup.sh"

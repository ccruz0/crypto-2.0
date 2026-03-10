#!/usr/bin/env bash
# Pop-up dialogs to enter exchange credentials, then POST to backend.
# macOS: uses osascript (native dialogs). Linux: falls back to read -p.
set -e
API_URL="${API_URL:-https://dashboard.hilovivo.com/api}"
ENDPOINT="/settings/exchange-credentials"
URL="${API_URL%/}${ENDPOINT}"

if [[ "$(uname -s)" == "Darwin" ]]; then
  API_KEY=$(osascript -e 'Tell application "System Events" to display dialog "Exchange API Key:" with title "Set Exchange Credentials" default answer "" with icon note with hidden answer' -e 'text returned of result' 2>/dev/null) || exit 0
  API_SECRET=$(osascript -e 'Tell application "System Events" to display dialog "Exchange API Secret:" with title "Set Exchange Credentials" default answer "" with icon note with hidden answer' -e 'text returned of result' 2>/dev/null) || exit 0
  ADMIN_KEY=$(osascript -e 'Tell application "System Events" to display dialog "Admin key (optional; leave empty if not set):" with title "Set Exchange Credentials" default answer "" with icon note with hidden answer' -e 'text returned of result' 2>/dev/null) || true
else
  echo "Exchange API Key:"
  read -r API_KEY
  echo "Exchange API Secret:"
  read -rs API_SECRET
  echo
  echo "Admin key (optional):"
  read -r ADMIN_KEY
fi

if [[ -z "$API_KEY" || -z "$API_SECRET" ]]; then
  echo "API Key and API Secret are required." >&2
  exit 1
fi

JSON=$(printf '%s' "{\"api_key\":$(echo -n "$API_KEY" | python3 -c 'import json,sys; print(json.dumps(sys.stdin.read()))'),\"api_secret\":$(echo -n "$API_SECRET" | python3 -c 'import json,sys; print(json.dumps(sys.stdin.read()))')}")

if [[ -n "$ADMIN_KEY" ]]; then
  RESP=$(curl -sS -w "\n%{http_code}" -X POST "$URL" -H "Content-Type: application/json" -H "X-Admin-Key: $ADMIN_KEY" -d "$JSON")
else
  RESP=$(curl -sS -w "\n%{http_code}" -X POST "$URL" -H "Content-Type: application/json" -d "$JSON")
fi

HTTP_CODE=$(echo "$RESP" | tail -n1)
BODY=$(echo "$RESP" | sed '$d')

if [[ "$HTTP_CODE" =~ ^2 ]]; then
  osascript -e "display dialog \"Credentials saved. Restart the backend container for them to take effect.\" with title \"Success\" buttons {\"OK\"} default button \"OK\" with icon note" 2>/dev/null || echo "Credentials saved. Restart the backend container for them to take effect."
else
  osascript -e "display dialog \"Request failed: $HTTP_CODE - $BODY\" with title \"Error\" buttons {\"OK\"} default button \"OK\" with icon stop" 2>/dev/null || { echo "Request failed: $HTTP_CODE"; echo "$BODY"; exit 1; }
fi

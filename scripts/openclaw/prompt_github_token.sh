#!/usr/bin/env bash
# Prompt for GitHub token via system popup (macOS or Linux), then save to ~/secrets/openclaw_token (600).
# Run: bash scripts/openclaw/prompt_github_token.sh
# Do not commit the token or this file with any token value.

set -e
SECRETS_DIR="${HOME}/secrets"
TOKEN_FILE="${SECRETS_DIR}/openclaw_token"
TOKEN=""

get_via_dialog() {
  if [[ "$(uname -s)" == "Darwin" ]]; then
    # macOS: osascript dialog (hidden answer = password-style)
    TOKEN=$(osascript -e 'text returned of (display dialog "Paste your GitHub fine-grained PAT for OpenClaw:" default answer "" with title "OpenClaw GitHub Token" with hidden answer)' 2>/dev/null || true)
  elif command -v zenity &>/dev/null; then
    TOKEN=$(zenity --password --title="OpenClaw GitHub Token" --text="Paste your GitHub fine-grained PAT:" 2>/dev/null || true)
  elif command -v kdialog &>/dev/null; then
    TOKEN=$(kdialog --password "Paste your GitHub fine-grained PAT for OpenClaw:" 2>/dev/null || true)
  fi
}

get_via_terminal() {
  read -r -s -p "GitHub fine-grained PAT (paste, then Enter): " TOKEN
  echo
}

mkdir -p "$SECRETS_DIR"
chmod 700 "$SECRETS_DIR"

get_via_dialog
if [[ -z "$TOKEN" ]]; then
  echo "No token from dialog; falling back to terminal prompt."
  get_via_terminal
fi

if [[ -z "$TOKEN" ]]; then
  echo "No token entered. Exiting." >&2
  exit 1
fi

echo -n "$TOKEN" > "$TOKEN_FILE"
chmod 600 "$TOKEN_FILE"
echo "Token saved to $TOKEN_FILE (600)."
unset TOKEN

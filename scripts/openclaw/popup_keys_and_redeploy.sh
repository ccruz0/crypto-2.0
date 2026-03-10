#!/usr/bin/env bash
# Prompt OpenAI/Anthropic keys via popup and redeploy OpenClaw on LAB.
# Usage: bash scripts/openclaw/popup_keys_and_redeploy.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
DEPLOY_SCRIPT="$SCRIPT_DIR/deploy_openclaw_lab_from_mac.sh"
KEY_CACHE_FILE="${OPENCLAW_KEY_CACHE_FILE:-$HOME/.openclaw/lab-provider-keys.env}"
FORCE_KEY_PROMPT="${OPENCLAW_FORCE_KEY_PROMPT:-0}"

openai_key=""
anthropic_key=""

load_cached_keys() {
  if [[ "$FORCE_KEY_PROMPT" == "1" ]]; then
    return
  fi
  if [[ -f "$KEY_CACHE_FILE" ]]; then
    # shellcheck disable=SC1090
    source "$KEY_CACHE_FILE"
    openai_key="${openai_key:-${OPENAI_API_KEY:-}}"
    anthropic_key="${anthropic_key:-${ANTHROPIC_API_KEY:-}}"
  fi
}

save_cached_keys() {
  mkdir -p "$(dirname "$KEY_CACHE_FILE")"
  chmod 700 "$(dirname "$KEY_CACHE_FILE")"
  local tmp_file
  tmp_file="$(mktemp)"
  {
    printf "OPENAI_API_KEY=%q\n" "$openai_key"
    if [[ -n "$anthropic_key" ]]; then
      printf "ANTHROPIC_API_KEY=%q\n" "$anthropic_key"
    else
      printf "ANTHROPIC_API_KEY=\n"
    fi
  } > "$tmp_file"
  chmod 600 "$tmp_file"
  mv "$tmp_file" "$KEY_CACHE_FILE"
}

ask_secret_dialog() {
  local title="$1"
  local prompt="$2"
  local value=""

  if [[ "$(uname -s)" == "Darwin" ]]; then
    value=$(osascript -e "text returned of (display dialog \"$prompt\" default answer \"\" with title \"$title\" with hidden answer)" 2>/dev/null || true)
  elif command -v zenity >/dev/null 2>&1; then
    value=$(zenity --password --title="$title" --text="$prompt" 2>/dev/null || true)
  elif command -v kdialog >/dev/null 2>&1; then
    value=$(kdialog --password "$prompt" 2>/dev/null || true)
  fi

  printf "%s" "$value"
}

ask_secret_terminal() {
  local prompt="$1"
  local value=""
  read -r -s -p "$prompt" value
  echo
  printf "%s" "$value"
}

load_cached_keys
echo "OpenClaw key setup: OpenAI + optional Anthropic"

if [[ -z "$openai_key" ]]; then
  openai_key="$(ask_secret_dialog "OpenClaw Key Setup" "Paste OPENAI_API_KEY (required):")"
  if [[ -z "$openai_key" ]]; then
    openai_key="$(ask_secret_terminal "OPENAI_API_KEY (required): ")"
  fi
else
  echo "Using cached OPENAI_API_KEY from $KEY_CACHE_FILE"
fi

if [[ -z "$openai_key" ]]; then
  echo "No OPENAI_API_KEY provided. Aborting." >&2
  exit 1
fi

if [[ -z "$anthropic_key" && "$FORCE_KEY_PROMPT" == "1" ]]; then
  anthropic_key="$(ask_secret_dialog "OpenClaw Key Setup" "Paste ANTHROPIC_API_KEY (optional, can be blank):")"
  if [[ -z "$anthropic_key" ]]; then
    anthropic_key="$(ask_secret_terminal "ANTHROPIC_API_KEY (optional, Enter to skip): ")"
  fi
fi

save_cached_keys

echo "Running LAB deploy with provided keys..."
if [[ -n "$anthropic_key" ]]; then
  OPENCLAW_IMAGE="ghcr.io/ccruz0/openclaw:latest" ANTHROPIC_API_KEY="$anthropic_key" OPENAI_API_KEY="$openai_key" "$DEPLOY_SCRIPT" deploy
else
  OPENCLAW_IMAGE="ghcr.io/ccruz0/openclaw:latest" OPENAI_API_KEY="$openai_key" "$DEPLOY_SCRIPT" deploy
fi

unset openai_key
unset anthropic_key
echo "Done. If UI was open, refresh OpenClaw in the browser."

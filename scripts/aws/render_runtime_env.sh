#!/usr/bin/env bash
set -euo pipefail
set +x 2>/dev/null || true

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$SCRIPT_DIR/../.."
ROOT_DIR="$(cd "$ROOT_DIR" && pwd)"

if [[ ! -f "$ROOT_DIR/docker-compose.yml" ]]; then
  SEARCH_DIR="$SCRIPT_DIR"
  while [[ "$SEARCH_DIR" != "/" ]]; do
    if [[ -f "$SEARCH_DIR/docker-compose.yml" ]]; then
      ROOT_DIR="$SEARCH_DIR"
      break
    fi
    SEARCH_DIR="$(dirname "$SEARCH_DIR")"
  done
fi

if [[ ! -f "$ROOT_DIR/docker-compose.yml" ]]; then
  echo "ERROR: repo root not found (docker-compose.yml missing)" >&2
  exit 1
fi

SECRETS_DIR="$ROOT_DIR/secrets"
RUNTIME_ENV="$SECRETS_DIR/runtime.env"
mkdir -p "$SECRETS_DIR"

SSM_BOT_TOKEN="/automated-trading-platform/prod/telegram/bot_token"
SSM_CHAT_ID="/automated-trading-platform/prod/telegram/chat_id"
SSM_ADMIN_KEY="/automated-trading-platform/prod/admin_actions_key"
SSM_DIAG_KEY="/automated-trading-platform/prod/diagnostics_api_key"

SOURCE="none"
BOT_TOKEN=""
CHAT_ID=""
ADMIN_KEY=""
DIAG_KEY=""

fetch_ssm() {
  local name="$1"
  aws ssm get-parameter --name "$name" --with-decryption --query "Parameter.Value" --output text 2>/dev/null
}

use_ssm=false
if command -v aws >/dev/null 2>&1; then
  if aws sts get-caller-identity >/dev/null 2>&1; then
    BT="$(fetch_ssm "$SSM_BOT_TOKEN" || true)"
    CI="$(fetch_ssm "$SSM_CHAT_ID" || true)"
    AK="$(fetch_ssm "$SSM_ADMIN_KEY" || true)"
    DK="$(fetch_ssm "$SSM_DIAG_KEY" || true)"
    if [[ -n "$BT" && -n "$CI" && -n "$AK" ]]; then
      BOT_TOKEN="$BT"
      CHAT_ID="$CI"
      ADMIN_KEY="$AK"
      DIAG_KEY="${DK:-$AK}"
      SOURCE="primary"
      use_ssm=true
    fi
  fi
fi

if [[ "$use_ssm" != "true" ]]; then
  ENV_FILE="$ROOT_DIR/.env.aws"
  if [[ ! -f "$ENV_FILE" ]]; then
    echo "ERROR: missing required keys (source=fallback unavailable)" >&2
    echo "Present: TELEGRAM_BOT_TOKEN=NO TELEGRAM_CHAT_ID=NO ADMIN_ACTIONS_KEY=NO DIAGNOSTICS_API_KEY=NO" >&2
    exit 1
  fi
  set -a
  # shellcheck disable=SC1090
  source "$ENV_FILE"
  set +a

  BOT_TOKEN="${TELEGRAM_BOT_TOKEN:-${TELEGRAM_BOT_TOKEN_AWS:-}}"
  CHAT_ID="${TELEGRAM_CHAT_ID_AWS:-${TELEGRAM_CHAT_ID:-}}"
  ADMIN_KEY="${ADMIN_ACTIONS_KEY:-${DIAGNOSTICS_API_KEY:-}}"
  DIAG_KEY="${DIAGNOSTICS_API_KEY:-$ADMIN_KEY}"
  SOURCE="fallback"
fi

missing=()
[[ -z "$BOT_TOKEN" ]] && missing+=("TELEGRAM_BOT_TOKEN")
[[ -z "$CHAT_ID" ]] && missing+=("TELEGRAM_CHAT_ID")
[[ -z "$ADMIN_KEY" ]] && missing+=("ADMIN_ACTIONS_KEY")

if (( ${#missing[@]} > 0 )); then
  echo "ERROR: missing required keys: ${missing[*]} (source=$SOURCE)" >&2
  echo "Present: TELEGRAM_BOT_TOKEN=$([[ -n "$BOT_TOKEN" ]] && echo YES || echo NO) TELEGRAM_CHAT_ID=$([[ -n "$CHAT_ID" ]] && echo YES || echo NO) ADMIN_ACTIONS_KEY=$([[ -n "$ADMIN_KEY" ]] && echo YES || echo NO) DIAGNOSTICS_API_KEY=$([[ -n "$DIAG_KEY" ]] && echo YES || echo NO)" >&2
  exit 1
fi

umask 077
{
  printf "TELEGRAM_BOT_TOKEN=%s\n" "$BOT_TOKEN"
  printf "TELEGRAM_CHAT_ID=%s\n" "$CHAT_ID"
  printf "ADMIN_ACTIONS_KEY=%s\n" "$ADMIN_KEY"
  printf "DIAGNOSTICS_API_KEY=%s\n" "$DIAG_KEY"
  printf "ENVIRONMENT=aws\n"
  printf "RUN_TELEGRAM=true\n"
} > "$RUNTIME_ENV"

echo "Rendered (source=$SOURCE)"
echo "Present: TELEGRAM_BOT_TOKEN=YES TELEGRAM_CHAT_ID=YES ADMIN_ACTIONS_KEY=YES DIAGNOSTICS_API_KEY=$([[ -n "$DIAG_KEY" ]] && echo YES || echo NO)"

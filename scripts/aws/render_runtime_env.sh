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
SSM_CHAT_ID_OPS="/automated-trading-platform/prod/telegram/chat_id_ops"
SSM_ADMIN_KEY="/automated-trading-platform/prod/admin_actions_key"
SSM_DIAG_KEY="/automated-trading-platform/prod/diagnostics_api_key"
SSM_ATP_API_KEY="/automated-trading-platform/prod/atp_api_key"
SSM_GITHUB_TOKEN="/automated-trading-platform/prod/github_token"
SSM_AWS_ACCESS_KEY="/automated-trading-platform/prod/aws_access_key_id"
SSM_AWS_SECRET_KEY="/automated-trading-platform/prod/aws_secret_access_key"
SSM_NOTION_API_KEY="/automated-trading-platform/prod/notion/api_key"
SSM_NOTION_TASK_DB="/automated-trading-platform/prod/notion/task_db"
SSM_NOTION_API_KEY_LAB="/automated-trading-platform/lab/notion/api_key"
SSM_ATP_CONTROL_CHAT_ID="/automated-trading-platform/prod/telegram/atp_control_chat_id"
SSM_ATP_CONTROL_BOT_TOKEN="/automated-trading-platform/prod/telegram/atp_control_bot_token"
NOTION_TASK_DB_DEFAULT="eb90cfa139f94724a8b476315908510a"

SOURCE="none"
BOT_TOKEN=""
CHAT_ID=""
CHAT_ID_OPS=""
ATP_CONTROL_CHAT_ID_VAL=""
ATP_CONTROL_BOT_TOKEN_VAL=""
ADMIN_KEY=""
DIAG_KEY=""
ATP_API_KEY=""
GITHUB_TOKEN=""
AWS_ACCESS_KEY_ID_VAL=""
AWS_SECRET_ACCESS_KEY_VAL=""
NOTION_API_KEY_VAL=""
NOTION_TASK_DB_VAL=""

SSM_REGION="${AWS_REGION:-${AWS_DEFAULT_REGION:-ap-southeast-1}}"
fetch_ssm() {
  local name="$1"
  aws ssm get-parameter --name "$name" --with-decryption --query "Parameter.Value" --output text --region "$SSM_REGION" 2>/dev/null
}

use_ssm=false
if command -v aws >/dev/null 2>&1; then
  if aws sts get-caller-identity >/dev/null 2>&1; then
    BT="$(fetch_ssm "$SSM_BOT_TOKEN" || true)"
    CI="$(fetch_ssm "$SSM_CHAT_ID" || true)"
    CIO="$(fetch_ssm "$SSM_CHAT_ID_OPS" || true)"
    AK="$(fetch_ssm "$SSM_ADMIN_KEY" || true)"
    DK="$(fetch_ssm "$SSM_DIAG_KEY" || true)"
    ATP="$(fetch_ssm "$SSM_ATP_API_KEY" || true)"
    GH="$(fetch_ssm "$SSM_GITHUB_TOKEN" || true)"
    AWS_ACCESS_KEY_ID_VAL="$(fetch_ssm "$SSM_AWS_ACCESS_KEY" || true)"
    AWS_SECRET_ACCESS_KEY_VAL="$(fetch_ssm "$SSM_AWS_SECRET_KEY" || true)"
    NOTION_API_KEY_VAL="$(fetch_ssm "$SSM_NOTION_API_KEY" || true)"
    NOTION_TASK_DB_VAL="$(fetch_ssm "$SSM_NOTION_TASK_DB" || true)"
    ATP_CONTROL_CHAT_ID_VAL="$(fetch_ssm "$SSM_ATP_CONTROL_CHAT_ID" || true)"
    ATP_CONTROL_BOT_TOKEN_VAL="$(fetch_ssm "$SSM_ATP_CONTROL_BOT_TOKEN" || true)"
    # LAB: if Notion not in prod SSM, try LAB SSM (instance role must have ssm:GetParameter for lab path)
    [[ -z "$NOTION_API_KEY_VAL" ]] && NOTION_API_KEY_VAL="$(fetch_ssm "$SSM_NOTION_API_KEY_LAB" || true)"
    [[ -z "$NOTION_TASK_DB_VAL" && -n "$NOTION_API_KEY_VAL" ]] && NOTION_TASK_DB_VAL="$NOTION_TASK_DB_DEFAULT"
    if [[ -n "$BT" && -n "$CI" && -n "$AK" ]]; then
      BOT_TOKEN="$BT"
      CHAT_ID="$CI"
      CHAT_ID_OPS="${CIO:-}"
      ADMIN_KEY="$AK"
      DIAG_KEY="${DK:-$AK}"
      ATP_API_KEY="$ATP"
      GITHUB_TOKEN="$GH"
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
  set +u
  # shellcheck disable=SC1090
  source "$ENV_FILE"
  set -u
  set +a

  BOT_TOKEN="${TELEGRAM_BOT_TOKEN:-${TELEGRAM_BOT_TOKEN_AWS:-}}"
  CHAT_ID="${TELEGRAM_CHAT_ID_AWS:-${TELEGRAM_CHAT_ID:-}}"
  CHAT_ID_OPS="${TELEGRAM_CHAT_ID_OPS:-}"
  ADMIN_KEY="${ADMIN_ACTIONS_KEY:-${DIAGNOSTICS_API_KEY:-}}"
  DIAG_KEY="${DIAGNOSTICS_API_KEY:-$ADMIN_KEY}"
  ATP_API_KEY="${ATP_API_KEY:-}"
  GITHUB_TOKEN="${GITHUB_TOKEN:-}"
  AWS_ACCESS_KEY_ID_VAL="${AWS_ACCESS_KEY_ID:-}"
  AWS_SECRET_ACCESS_KEY_VAL="${AWS_SECRET_ACCESS_KEY:-}"
  NOTION_API_KEY_VAL="${NOTION_API_KEY:-}"
  NOTION_TASK_DB_VAL="${NOTION_TASK_DB:-}"
  ATP_CONTROL_CHAT_ID_VAL="${TELEGRAM_ATP_CONTROL_CHAT_ID:-}"
  ATP_CONTROL_BOT_TOKEN_VAL="${TELEGRAM_ATP_CONTROL_BOT_TOKEN:-}"
  SOURCE="fallback"
  # LAB: try LAB SSM for Notion if still missing (no manual secret input)
  if command -v aws >/dev/null 2>&1 && aws sts get-caller-identity >/dev/null 2>&1; then
    [[ -z "$NOTION_API_KEY_VAL" ]] && NOTION_API_KEY_VAL="$(fetch_ssm "$SSM_NOTION_API_KEY_LAB" || true)"
    [[ -z "$NOTION_TASK_DB_VAL" && -n "$NOTION_API_KEY_VAL" ]] && NOTION_TASK_DB_VAL="$NOTION_TASK_DB_DEFAULT"
  fi
fi

# Use ATP Control token/chat for polling when primary not set (ensures /task works)
[[ -z "$BOT_TOKEN" && -n "$ATP_CONTROL_BOT_TOKEN_VAL" ]] && BOT_TOKEN="$ATP_CONTROL_BOT_TOKEN_VAL" && echo "Using ATP Control token for TELEGRAM_BOT_TOKEN (primary not set)" && SOURCE="${SOURCE}+atp_control_fallback"
[[ -z "$CHAT_ID" && -n "$ATP_CONTROL_CHAT_ID_VAL" ]] && CHAT_ID="$ATP_CONTROL_CHAT_ID_VAL" && echo "Using ATP Control chat_id for TELEGRAM_CHAT_ID (primary not set)" && SOURCE="${SOURCE}+atp_control_chat_fallback"

missing=()
[[ -z "$BOT_TOKEN" ]] && missing+=("TELEGRAM_BOT_TOKEN")
[[ -z "$CHAT_ID" ]] && missing+=("TELEGRAM_CHAT_ID")
[[ -z "$ADMIN_KEY" ]] && missing+=("ADMIN_ACTIONS_KEY")

if (( ${#missing[@]} > 0 )); then
  echo "ERROR: missing required keys: ${missing[*]} (source=$SOURCE)" >&2
  echo "Present: TELEGRAM_BOT_TOKEN=$([[ -n "$BOT_TOKEN" ]] && echo YES || echo NO) TELEGRAM_CHAT_ID=$([[ -n "$CHAT_ID" ]] && echo YES || echo NO) ADMIN_ACTIONS_KEY=$([[ -n "$ADMIN_KEY" ]] && echo YES || echo NO) DIAGNOSTICS_API_KEY=$([[ -n "$DIAG_KEY" ]] && echo YES || echo NO)" >&2
  exit 1
fi

# ATP_API_KEY: from SSM/fallback or generate if missing (for x-api-key header)
if [[ -z "$ATP_API_KEY" ]]; then
  if command -v python3 >/dev/null 2>&1; then
    ATP_API_KEY="$(python3 -c "import secrets; print(secrets.token_urlsafe(32))")"
  fi
fi

umask 077
{
  printf "TELEGRAM_BOT_TOKEN=%s\n" "$BOT_TOKEN"
  printf "TELEGRAM_CHAT_ID=%s\n" "$CHAT_ID"
  printf "TELEGRAM_CHAT_ID_AWS=%s\n" "$CHAT_ID"
  [[ -n "$CHAT_ID_OPS" ]] && printf "TELEGRAM_CHAT_ID_OPS=%s\n" "$CHAT_ID_OPS"
  printf "ADMIN_ACTIONS_KEY=%s\n" "$ADMIN_KEY"
  printf "DIAGNOSTICS_API_KEY=%s\n" "$DIAG_KEY"
  printf "ATP_API_KEY=%s\n" "${ATP_API_KEY:-}"
  printf "ENVIRONMENT=aws\n"
  printf "RUN_TELEGRAM=true\n"
  [[ -n "$GITHUB_TOKEN" ]] && printf "GITHUB_TOKEN=%s\n" "$GITHUB_TOKEN"
} > "$RUNTIME_ENV"

# Optional health config: market data staleness threshold (minutes). See docs/MARKET_UPDATER_HARDENING_PLAN.md.
echo "HEALTH_STALE_MARKET_MINUTES=15" >> "$RUNTIME_ENV"

# ATP SSM runner: explicit AWS credentials for run-atp-command (if instance metadata unavailable in container)
[[ -n "$AWS_ACCESS_KEY_ID_VAL" && -n "$AWS_SECRET_ACCESS_KEY_VAL" ]] && {
  printf "AWS_ACCESS_KEY_ID=%s\n" "$AWS_ACCESS_KEY_ID_VAL" >> "$RUNTIME_ENV"
  printf "AWS_SECRET_ACCESS_KEY=%s\n" "$AWS_SECRET_ACCESS_KEY_VAL" >> "$RUNTIME_ENV"
  echo "AWS_DEFAULT_REGION=ap-southeast-1" >> "$RUNTIME_ENV"
}

# OpenClaw cost optimization: verification uses cheap model (add OPENCLAW_API_TOKEN, OPENCLAW_API_URL manually if using OpenClaw)
echo "OPENCLAW_VERIFICATION_PRIMARY_MODEL=openai/gpt-4o-mini" >> "$RUNTIME_ENV"
# Task-type routing: doc/monitoring use cheap chain; bug tasks use main chain
echo "OPENCLAW_CHEAP_TASK_TYPES=doc,documentation,monitoring,triage" >> "$RUNTIME_ENV"
echo "OPENCLAW_CHEAP_MODEL_CHAIN=openai/gpt-4o-mini" >> "$RUNTIME_ENV"
# Optional caps (not written by default): OPENCLAW_TASK_DETAILS_MAX_CHARS, OPENCLAW_MAX_OUTPUT_TOKENS — see secrets/runtime.env.example

# Notion (AI Task System): from SSM or fallback; if primary but Notion not in SSM (e.g. LAB), append from .env.aws when present
if [[ -n "$NOTION_API_KEY_VAL" ]]; then
  printf "NOTION_API_KEY=%s\n" "$NOTION_API_KEY_VAL" >> "$RUNTIME_ENV"
fi
if [[ -n "$NOTION_TASK_DB_VAL" ]]; then
  printf "NOTION_TASK_DB=%s\n" "$NOTION_TASK_DB_VAL" >> "$RUNTIME_ENV"
fi
if [[ "$SOURCE" == "primary" && ( -z "$NOTION_API_KEY_VAL" || -z "$NOTION_TASK_DB_VAL" ) ]] && [[ -f "$ROOT_DIR/.env.aws" ]]; then
  ( set +u; set -a; source "$ROOT_DIR/.env.aws" 2>/dev/null; set +a; set -u
    if [[ -n "${NOTION_API_KEY:-}" ]] && ! grep -q '^NOTION_API_KEY=' "$RUNTIME_ENV" 2>/dev/null; then printf "NOTION_API_KEY=%s\n" "${NOTION_API_KEY:-}" >> "$RUNTIME_ENV"; fi
    if [[ -n "${NOTION_TASK_DB:-}" ]] && ! grep -q '^NOTION_TASK_DB=' "$RUNTIME_ENV" 2>/dev/null; then printf "NOTION_TASK_DB=%s\n" "${NOTION_TASK_DB:-}" >> "$RUNTIME_ENV"; fi
  )
fi

# ATP Control (@ATP_control_bot): tasks, approvals, investigations. Auto-authorizes channel for commands.
[[ -n "$ATP_CONTROL_CHAT_ID_VAL" ]] && printf "TELEGRAM_ATP_CONTROL_CHAT_ID=%s\n" "$ATP_CONTROL_CHAT_ID_VAL" >> "$RUNTIME_ENV"
[[ -n "$ATP_CONTROL_BOT_TOKEN_VAL" ]] && printf "TELEGRAM_ATP_CONTROL_BOT_TOKEN=%s\n" "$ATP_CONTROL_BOT_TOKEN_VAL" >> "$RUNTIME_ENV"

echo "Rendered (source=$SOURCE)"
echo "Present: TELEGRAM_BOT_TOKEN=YES TELEGRAM_CHAT_ID=YES ADMIN_ACTIONS_KEY=YES DIAGNOSTICS_API_KEY=$([[ -n "$DIAG_KEY" ]] && echo YES || echo NO) ATP_API_KEY=$([[ -n "$ATP_API_KEY" ]] && echo YES || echo NO) GITHUB_TOKEN=$([[ -n "$GITHUB_TOKEN" ]] && echo YES || echo NO) NOTION_API_KEY=$([[ -n "$NOTION_API_KEY_VAL" ]] && echo YES || echo NO) NOTION_TASK_DB=$([[ -n "$NOTION_TASK_DB_VAL" ]] && echo YES || echo NO)"

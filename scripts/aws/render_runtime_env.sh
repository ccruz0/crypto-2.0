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
SSM_GITHUB_APP_ID="/automated-trading-platform/prod/github_app/app_id"
SSM_GITHUB_APP_INSTALLATION_ID="/automated-trading-platform/prod/github_app/installation_id"
SSM_GITHUB_APP_PRIVATE_KEY_B64="/automated-trading-platform/prod/github_app/private_key_b64"
SSM_GITHUB_APP_ID_LAB="/automated-trading-platform/lab/github_app/app_id"
SSM_GITHUB_APP_INSTALLATION_ID_LAB="/automated-trading-platform/lab/github_app/installation_id"
SSM_GITHUB_APP_PRIVATE_KEY_B64_LAB="/automated-trading-platform/lab/github_app/private_key_b64"
SSM_AWS_ACCESS_KEY="/automated-trading-platform/prod/aws_access_key_id"
SSM_AWS_SECRET_KEY="/automated-trading-platform/prod/aws_secret_access_key"
SSM_NOTION_API_KEY="/automated-trading-platform/prod/notion/api_key"
SSM_NOTION_TASK_DB="/automated-trading-platform/prod/notion/task_db"
SSM_NOTION_API_KEY_LAB="/automated-trading-platform/lab/notion/api_key"
SSM_ATP_CONTROL_CHAT_ID="/automated-trading-platform/prod/telegram/atp_control_chat_id"
SSM_ATP_CONTROL_BOT_TOKEN="/automated-trading-platform/prod/telegram/atp_control_bot_token"
SSM_EXCHANGE_API_KEY="/automated-trading-platform/prod/exchange_custom/api_key"
SSM_EXCHANGE_API_SECRET="/automated-trading-platform/prod/exchange_custom/api_secret"
# Brief API (/api/brief/*) — must survive Session Manager renders (2026-08-06 wipe).
SSM_BRIEF_API_KEY="/automated-trading-platform/prod/brief/api_key"
SSM_BRIEF_MAILBOXES_PATH="/automated-trading-platform/prod/brief/mailboxes_path"
SSM_BRIEF_RATE_LIMIT="/automated-trading-platform/prod/brief/rate_limit_per_minute"
SSM_BRIEF_ICS_URLS="/automated-trading-platform/prod/brief/ics_urls"
SSM_TELEGRAM_API_ID="/automated-trading-platform/prod/telegram/api_id"
SSM_TELEGRAM_API_HASH="/automated-trading-platform/prod/telegram/api_hash"
SSM_TELEGRAM_SESSION_PATH="/automated-trading-platform/prod/telegram/session_path"
NOTION_TASK_DB_DEFAULT="eb90cfa139f94724a8b476315908510a"
BRIEF_MAILBOXES_PATH_DEFAULT="/app/secrets/brief_mailboxes.json"
BRIEF_RATE_LIMIT_DEFAULT="30"
TELEGRAM_SESSION_PATH_DEFAULT="/data/telegram/hilovivo.session"

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
GITHUB_APP_ID_VAL=""
GITHUB_APP_INSTALLATION_ID_VAL=""
GITHUB_APP_PRIVATE_KEY_B64_VAL=""
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
    GITHUB_APP_ID_VAL="$(fetch_ssm "$SSM_GITHUB_APP_ID" || true)"
    GITHUB_APP_INSTALLATION_ID_VAL="$(fetch_ssm "$SSM_GITHUB_APP_INSTALLATION_ID" || true)"
    GITHUB_APP_PRIVATE_KEY_B64_VAL="$(fetch_ssm "$SSM_GITHUB_APP_PRIVATE_KEY_B64" || true)"
    [[ -z "$GITHUB_APP_ID_VAL" ]] && GITHUB_APP_ID_VAL="$(fetch_ssm "$SSM_GITHUB_APP_ID_LAB" || true)"
    [[ -z "$GITHUB_APP_INSTALLATION_ID_VAL" ]] && GITHUB_APP_INSTALLATION_ID_VAL="$(fetch_ssm "$SSM_GITHUB_APP_INSTALLATION_ID_LAB" || true)"
    [[ -z "$GITHUB_APP_PRIVATE_KEY_B64_VAL" ]] && GITHUB_APP_PRIVATE_KEY_B64_VAL="$(fetch_ssm "$SSM_GITHUB_APP_PRIVATE_KEY_B64_LAB" || true)"
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
  GITHUB_APP_ID_VAL="${GITHUB_APP_ID:-}"
  GITHUB_APP_INSTALLATION_ID_VAL="${GITHUB_APP_INSTALLATION_ID:-}"
  GITHUB_APP_PRIVATE_KEY_B64_VAL="${GITHUB_APP_PRIVATE_KEY_B64:-}"
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

# Read a single KEY=value from existing runtime.env (never print values).
read_runtime_env_flag() {
  local key="$1"
  if [[ -f "$RUNTIME_ENV" ]]; then
    grep -E "^${key}=" "$RUNTIME_ENV" 2>/dev/null | cut -d= -f2- | head -1 || true
  fi
}

# Preserve exchange credentials before overwrite (never print values)
PRESERVE_EXCHANGE_API_KEY="$(read_runtime_env_flag EXCHANGE_CUSTOM_API_KEY)"
PRESERVE_EXCHANGE_API_SECRET="$(read_runtime_env_flag EXCHANGE_CUSTOM_API_SECRET)"

# Preserve Jarvis Phase 4B/5 safety flags before overwrite (never print values).
PRESERVE_JARVIS_4B_PROPOSALS_ENABLED="$(read_runtime_env_flag JARVIS_4B_PROPOSALS_ENABLED)"
PRESERVE_JARVIS_4B_MIN_CONFIDENCE="$(read_runtime_env_flag JARVIS_4B_MIN_CONFIDENCE)"
PRESERVE_JARVIS_PATCH_APPLY_ENABLED="$(read_runtime_env_flag JARVIS_PATCH_APPLY_ENABLED)"
PRESERVE_JARVIS_PR_CREATION_ENABLED="$(read_runtime_env_flag JARVIS_PR_CREATION_ENABLED)"
PRESERVE_JARVIS_GITHUB_WRITE_ENABLED="$(read_runtime_env_flag JARVIS_GITHUB_WRITE_ENABLED)"
PRESERVE_JARVIS_REQUIRE_DOUBLE_APPROVAL="$(read_runtime_env_flag JARVIS_REQUIRE_DOUBLE_APPROVAL)"
# Preserve Jarvis Telegram control allowlists (alert CTAs /mission) before overwrite.
PRESERVE_JARVIS_TELEGRAM_ENABLED="$(read_runtime_env_flag JARVIS_TELEGRAM_ENABLED)"
PRESERVE_JARVIS_TELEGRAM_CHAT_ID="$(read_runtime_env_flag JARVIS_TELEGRAM_CHAT_ID)"
PRESERVE_TELEGRAM_ALLOWED_CHAT_IDS="$(read_runtime_env_flag TELEGRAM_ALLOWED_CHAT_IDS)"
PRESERVE_TELEGRAM_ALLOWED_USER_IDS="$(read_runtime_env_flag TELEGRAM_ALLOWED_USER_IDS)"
PRESERVE_TELEGRAM_AUTH_USER_ID="$(read_runtime_env_flag TELEGRAM_AUTH_USER_ID)"
# Preserve brief + Telethon user-API keys before overwrite (never print values).
PRESERVE_BRIEF_API_KEY="$(read_runtime_env_flag BRIEF_API_KEY)"
PRESERVE_BRIEF_MAILBOXES_PATH="$(read_runtime_env_flag BRIEF_MAILBOXES_PATH)"
PRESERVE_BRIEF_RATE_LIMIT_PER_MINUTE="$(read_runtime_env_flag BRIEF_RATE_LIMIT_PER_MINUTE)"
PRESERVE_BRIEF_ICS_URLS="$(read_runtime_env_flag BRIEF_ICS_URLS)"
PRESERVE_TELEGRAM_API_ID="$(read_runtime_env_flag TELEGRAM_API_ID)"
PRESERVE_TELEGRAM_API_HASH="$(read_runtime_env_flag TELEGRAM_API_HASH)"
PRESERVE_TELEGRAM_SESSION_PATH="$(read_runtime_env_flag TELEGRAM_SESSION_PATH)"
EXCHANGE_API_KEY_VAL=""
EXCHANGE_API_SECRET_VAL=""
EXCHANGE_CREDS_SOURCE="none"
if command -v aws >/dev/null 2>&1 && aws sts get-caller-identity >/dev/null 2>&1; then
  EXCHANGE_API_KEY_VAL="$(fetch_ssm "$SSM_EXCHANGE_API_KEY" || true)"
  EXCHANGE_API_SECRET_VAL="$(fetch_ssm "$SSM_EXCHANGE_API_SECRET" || true)"
  [[ -n "$EXCHANGE_API_KEY_VAL" && -n "$EXCHANGE_API_SECRET_VAL" ]] && EXCHANGE_CREDS_SOURCE="ssm"
fi
if [[ -z "$EXCHANGE_API_KEY_VAL" || -z "$EXCHANGE_API_SECRET_VAL" ]]; then
  if [[ -n "$PRESERVE_EXCHANGE_API_KEY" && -n "$PRESERVE_EXCHANGE_API_SECRET" ]]; then
    EXCHANGE_API_KEY_VAL="$PRESERVE_EXCHANGE_API_KEY"
    EXCHANGE_API_SECRET_VAL="$PRESERVE_EXCHANGE_API_SECRET"
    EXCHANGE_CREDS_SOURCE="preserved"
  elif [[ -f "$ROOT_DIR/.env.aws" ]]; then
    ( set +u; set -a; source "$ROOT_DIR/.env.aws" 2>/dev/null; set +a; set -u
      EXCHANGE_API_KEY_VAL="${EXCHANGE_CUSTOM_API_KEY:-}"
      EXCHANGE_API_SECRET_VAL="${EXCHANGE_CUSTOM_API_SECRET:-}"
    )
    [[ -n "$EXCHANGE_API_KEY_VAL" && -n "$EXCHANGE_API_SECRET_VAL" ]] && EXCHANGE_CREDS_SOURCE="env.aws"
  fi
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
  [[ -n "$GITHUB_APP_ID_VAL" ]] && printf "GITHUB_APP_ID=%s\n" "$GITHUB_APP_ID_VAL"
  [[ -n "$GITHUB_APP_INSTALLATION_ID_VAL" ]] && printf "GITHUB_APP_INSTALLATION_ID=%s\n" "$GITHUB_APP_INSTALLATION_ID_VAL"
  [[ -n "$GITHUB_APP_PRIVATE_KEY_B64_VAL" ]] && printf "GITHUB_APP_PRIVATE_KEY_B64=%s\n" "$GITHUB_APP_PRIVATE_KEY_B64_VAL"
} > "$RUNTIME_ENV"

# When source=primary, .env.aws can override GitHub App keys (operator/LAB override).
if [[ "$SOURCE" == "primary" && -f "$ROOT_DIR/.env.aws" ]]; then
  ( set +u; set -a; source "$ROOT_DIR/.env.aws" 2>/dev/null; set +a; set -u
    if [[ -n "${GITHUB_APP_ID:-}" ]]; then
      if grep -q '^GITHUB_APP_ID=' "$RUNTIME_ENV" 2>/dev/null; then
        sed -i "s|^GITHUB_APP_ID=.*|GITHUB_APP_ID=${GITHUB_APP_ID}|" "$RUNTIME_ENV"
      else
        printf "GITHUB_APP_ID=%s\n" "${GITHUB_APP_ID}" >> "$RUNTIME_ENV"
      fi
    fi
    if [[ -n "${GITHUB_APP_INSTALLATION_ID:-}" ]]; then
      if grep -q '^GITHUB_APP_INSTALLATION_ID=' "$RUNTIME_ENV" 2>/dev/null; then
        sed -i "s|^GITHUB_APP_INSTALLATION_ID=.*|GITHUB_APP_INSTALLATION_ID=${GITHUB_APP_INSTALLATION_ID}|" "$RUNTIME_ENV"
      else
        printf "GITHUB_APP_INSTALLATION_ID=%s\n" "${GITHUB_APP_INSTALLATION_ID}" >> "$RUNTIME_ENV"
      fi
    fi
    if [[ -n "${GITHUB_APP_PRIVATE_KEY_B64:-}" ]]; then
      if grep -q '^GITHUB_APP_PRIVATE_KEY_B64=' "$RUNTIME_ENV" 2>/dev/null; then
        sed -i "s|^GITHUB_APP_PRIVATE_KEY_B64=.*|GITHUB_APP_PRIVATE_KEY_B64=${GITHUB_APP_PRIVATE_KEY_B64}|" "$RUNTIME_ENV"
      else
        printf "GITHUB_APP_PRIVATE_KEY_B64=%s\n" "${GITHUB_APP_PRIVATE_KEY_B64}" >> "$RUNTIME_ENV"
      fi
    fi
  )
fi

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
# Gateway supports max_output_tokens on POST /v1/responses (best-effort; see docs.openclaw.ai gateway OpenResponses)
echo "OPENCLAW_MAX_OUTPUT_TOKENS=8192" >> "$RUNTIME_ENV"

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

# Jarvis Telegram control (investigation alert CTAs + /mission). Operator private id is known.
# Prefer preserved / .env.aws values; always ensure operator 839853931 is on the user allowlist.
OPERATOR_TG_USER_ID="839853931"
JARVIS_TG_ENABLED_VAL="${PRESERVE_JARVIS_TELEGRAM_ENABLED:-}"
JARVIS_TG_CHAT_VAL="${PRESERVE_JARVIS_TELEGRAM_CHAT_ID:-}"
ALLOWED_CHATS_VAL="${PRESERVE_TELEGRAM_ALLOWED_CHAT_IDS:-}"
ALLOWED_USERS_VAL="${PRESERVE_TELEGRAM_ALLOWED_USER_IDS:-}"
AUTH_USER_VAL="${PRESERVE_TELEGRAM_AUTH_USER_ID:-}"
_read_env_aws_key() {
  local key="$1"
  if [[ -f "$ROOT_DIR/.env.aws" ]]; then
    grep -E "^${key}=" "$ROOT_DIR/.env.aws" 2>/dev/null | cut -d= -f2- | head -1 || true
  fi
}
if [[ -z "$JARVIS_TG_ENABLED_VAL" ]]; then
  JARVIS_TG_ENABLED_VAL="$(_read_env_aws_key JARVIS_TELEGRAM_ENABLED)"
fi
if [[ -z "$JARVIS_TG_CHAT_VAL" ]]; then
  JARVIS_TG_CHAT_VAL="$(_read_env_aws_key JARVIS_TELEGRAM_CHAT_ID)"
fi
if [[ -z "$ALLOWED_CHATS_VAL" ]]; then
  ALLOWED_CHATS_VAL="$(_read_env_aws_key TELEGRAM_ALLOWED_CHAT_IDS)"
fi
if [[ -z "$ALLOWED_USERS_VAL" ]]; then
  ALLOWED_USERS_VAL="$(_read_env_aws_key TELEGRAM_ALLOWED_USER_IDS)"
fi
if [[ -z "$AUTH_USER_VAL" ]]; then
  AUTH_USER_VAL="$(_read_env_aws_key TELEGRAM_AUTH_USER_ID)"
fi
[[ -z "$JARVIS_TG_ENABLED_VAL" ]] && JARVIS_TG_ENABLED_VAL="true"
[[ -z "$JARVIS_TG_CHAT_VAL" ]] && JARVIS_TG_CHAT_VAL="${CHAT_ID}"
# Build comma-separated chat allowlist: destinations + operator DM.
_chat_parts=()
[[ -n "$ALLOWED_CHATS_VAL" ]] && _chat_parts+=("$ALLOWED_CHATS_VAL")
[[ -n "$CHAT_ID" ]] && _chat_parts+=("$CHAT_ID")
[[ -n "$ATP_CONTROL_CHAT_ID_VAL" ]] && _chat_parts+=("$ATP_CONTROL_CHAT_ID_VAL")
[[ -n "$JARVIS_TG_CHAT_VAL" ]] && _chat_parts+=("$JARVIS_TG_CHAT_VAL")
_chat_parts+=("$OPERATOR_TG_USER_ID")
ALLOWED_CHATS_VAL="$(printf "%s," "${_chat_parts[@]}" | sed 's/,$//' | tr ',' '\n' | sed '/^$/d' | awk '!seen[$0]++' | paste -sd, -)"
# User allowlist: preserved + auth users + operator.
_user_parts=()
[[ -n "$ALLOWED_USERS_VAL" ]] && _user_parts+=("$ALLOWED_USERS_VAL")
[[ -n "$AUTH_USER_VAL" ]] && _user_parts+=("$AUTH_USER_VAL")
_user_parts+=("$OPERATOR_TG_USER_ID")
ALLOWED_USERS_VAL="$(printf "%s," "${_user_parts[@]}" | sed 's/,$//' | tr ',' '\n' | sed '/^$/d' | awk '!seen[$0]++' | paste -sd, -)"
# Ensure TELEGRAM_AUTH_USER_ID includes the operator (legacy command auth path).
if [[ -z "$AUTH_USER_VAL" ]]; then
  AUTH_USER_VAL="$OPERATOR_TG_USER_ID"
elif [[ ",${AUTH_USER_VAL}," != *",${OPERATOR_TG_USER_ID},"* ]]; then
  AUTH_USER_VAL="${AUTH_USER_VAL},${OPERATOR_TG_USER_ID}"
fi
printf "JARVIS_TELEGRAM_ENABLED=%s\n" "$JARVIS_TG_ENABLED_VAL" >> "$RUNTIME_ENV"
printf "JARVIS_TELEGRAM_CHAT_ID=%s\n" "$JARVIS_TG_CHAT_VAL" >> "$RUNTIME_ENV"
printf "TELEGRAM_ALLOWED_CHAT_IDS=%s\n" "$ALLOWED_CHATS_VAL" >> "$RUNTIME_ENV"
printf "TELEGRAM_ALLOWED_USER_IDS=%s\n" "$ALLOWED_USERS_VAL" >> "$RUNTIME_ENV"
printf "TELEGRAM_AUTH_USER_ID=%s\n" "$AUTH_USER_VAL" >> "$RUNTIME_ENV"
echo "JarvisTelegram allowlists: enabled=${JARVIS_TG_ENABLED_VAL} chats_set=YES users_include_operator=YES"

# GitHub auth mode (after all merges): App preferred; PAT-only sets legacy escape hatch for PR #32+.
GITHUB_APP_ALL=no
grep -q '^GITHUB_APP_ID=' "$RUNTIME_ENV" 2>/dev/null \
  && grep -q '^GITHUB_APP_INSTALLATION_ID=' "$RUNTIME_ENV" 2>/dev/null \
  && grep -q '^GITHUB_APP_PRIVATE_KEY_B64=' "$RUNTIME_ENV" 2>/dev/null \
  && GITHUB_APP_ALL=YES
HAS_GITHUB_PAT=no
grep -q '^GITHUB_TOKEN=' "$RUNTIME_ENV" 2>/dev/null && HAS_GITHUB_PAT=YES
GITHUB_AUTH_MODE=none
if [[ "$GITHUB_APP_ALL" == "YES" ]]; then
  GITHUB_AUTH_MODE=github_app
  if grep -q '^ALLOW_LEGACY_GITHUB_PAT=' "$RUNTIME_ENV" 2>/dev/null; then
    sed -i '/^ALLOW_LEGACY_GITHUB_PAT=/d' "$RUNTIME_ENV"
  fi
elif [[ "$HAS_GITHUB_PAT" == "YES" ]]; then
  GITHUB_AUTH_MODE=legacy_transition
  if grep -q '^ALLOW_LEGACY_GITHUB_PAT=' "$RUNTIME_ENV" 2>/dev/null; then
    sed -i 's|^ALLOW_LEGACY_GITHUB_PAT=.*|ALLOW_LEGACY_GITHUB_PAT=true|' "$RUNTIME_ENV"
  else
    printf "ALLOW_LEGACY_GITHUB_PAT=true\n" >> "$RUNTIME_ENV"
  fi
else
  if grep -q '^ALLOW_LEGACY_GITHUB_PAT=' "$RUNTIME_ENV" 2>/dev/null; then
    sed -i '/^ALLOW_LEGACY_GITHUB_PAT=/d' "$RUNTIME_ENV"
  fi
fi

# Crypto.com exchange credentials (SSM > preserved runtime.env > .env.aws). Never echo values.
if [[ -n "$EXCHANGE_API_KEY_VAL" && -n "$EXCHANGE_API_SECRET_VAL" ]]; then
  grep -q '^EXCHANGE_CUSTOM_API_KEY=' "$RUNTIME_ENV" 2>/dev/null && sed -i '/^EXCHANGE_CUSTOM_API_KEY=/d' "$RUNTIME_ENV"
  grep -q '^EXCHANGE_CUSTOM_API_SECRET=' "$RUNTIME_ENV" 2>/dev/null && sed -i '/^EXCHANGE_CUSTOM_API_SECRET=/d' "$RUNTIME_ENV"
  printf "EXCHANGE_CUSTOM_API_KEY=%s\n" "$EXCHANGE_API_KEY_VAL" >> "$RUNTIME_ENV"
  printf "EXCHANGE_CUSTOM_API_SECRET=%s\n" "$EXCHANGE_API_SECRET_VAL" >> "$RUNTIME_ENV"
fi

# Jarvis Phase 4B/5 safety gates: preserve existing runtime.env values or apply safe defaults.
# Phase 4B off unless explicitly enabled; Phase 5 off; double approval on by default.
JARVIS_4B_PROPOSALS_ENABLED="${PRESERVE_JARVIS_4B_PROPOSALS_ENABLED:-false}"
JARVIS_4B_MIN_CONFIDENCE="${PRESERVE_JARVIS_4B_MIN_CONFIDENCE:-50}"
JARVIS_PATCH_APPLY_ENABLED="${PRESERVE_JARVIS_PATCH_APPLY_ENABLED:-false}"
JARVIS_PR_CREATION_ENABLED="${PRESERVE_JARVIS_PR_CREATION_ENABLED:-false}"
JARVIS_GITHUB_WRITE_ENABLED="${PRESERVE_JARVIS_GITHUB_WRITE_ENABLED:-false}"
JARVIS_REQUIRE_DOUBLE_APPROVAL="${PRESERVE_JARVIS_REQUIRE_DOUBLE_APPROVAL:-true}"
for _jarvis_key in \
  JARVIS_4B_PROPOSALS_ENABLED \
  JARVIS_4B_MIN_CONFIDENCE \
  JARVIS_PATCH_APPLY_ENABLED \
  JARVIS_PR_CREATION_ENABLED \
  JARVIS_GITHUB_WRITE_ENABLED \
  JARVIS_REQUIRE_DOUBLE_APPROVAL; do
  grep -q "^${_jarvis_key}=" "$RUNTIME_ENV" 2>/dev/null && sed -i "/^${_jarvis_key}=/d" "$RUNTIME_ENV"
done
printf "JARVIS_4B_PROPOSALS_ENABLED=%s\n" "$JARVIS_4B_PROPOSALS_ENABLED" >> "$RUNTIME_ENV"
printf "JARVIS_4B_MIN_CONFIDENCE=%s\n" "$JARVIS_4B_MIN_CONFIDENCE" >> "$RUNTIME_ENV"
printf "JARVIS_PATCH_APPLY_ENABLED=%s\n" "$JARVIS_PATCH_APPLY_ENABLED" >> "$RUNTIME_ENV"
printf "JARVIS_PR_CREATION_ENABLED=%s\n" "$JARVIS_PR_CREATION_ENABLED" >> "$RUNTIME_ENV"
printf "JARVIS_GITHUB_WRITE_ENABLED=%s\n" "$JARVIS_GITHUB_WRITE_ENABLED" >> "$RUNTIME_ENV"
printf "JARVIS_REQUIRE_DOUBLE_APPROVAL=%s\n" "$JARVIS_REQUIRE_DOUBLE_APPROVAL" >> "$RUNTIME_ENV"
JARVIS_4B_SOURCE=default
[[ -n "$PRESERVE_JARVIS_4B_PROPOSALS_ENABLED" ]] && JARVIS_4B_SOURCE=preserved
JARVIS_PHASE5_SOURCE=default
if [[ -n "$PRESERVE_JARVIS_PATCH_APPLY_ENABLED" || -n "$PRESERVE_JARVIS_PR_CREATION_ENABLED" || -n "$PRESERVE_JARVIS_GITHUB_WRITE_ENABLED" || -n "$PRESERVE_JARVIS_REQUIRE_DOUBLE_APPROVAL" ]]; then
  JARVIS_PHASE5_SOURCE=preserved
fi

# Brief API + Telethon user session: SSM > preserved runtime.env > .env.aws > safe defaults for paths.
# Without BRIEF_API_KEY the backend returns brief_not_configured (nginx masks as upstream_unavailable).
# TELEGRAM_API_ID + TELEGRAM_API_HASH are a pair (same rule as EXCHANGE_CUSTOM_*): never mix sources.
BRIEF_API_KEY_VAL=""
BRIEF_MAILBOXES_PATH_VAL=""
BRIEF_RATE_LIMIT_VAL=""
BRIEF_ICS_URLS_VAL=""
TELEGRAM_API_ID_VAL=""
TELEGRAM_API_HASH_VAL=""
TELEGRAM_SESSION_PATH_VAL=""
BRIEF_SOURCE="none"
TELEGRAM_USER_API_SOURCE="none"
if command -v aws >/dev/null 2>&1 && aws sts get-caller-identity >/dev/null 2>&1; then
  BRIEF_API_KEY_VAL="$(fetch_ssm "$SSM_BRIEF_API_KEY" || true)"
  BRIEF_MAILBOXES_PATH_VAL="$(fetch_ssm "$SSM_BRIEF_MAILBOXES_PATH" || true)"
  BRIEF_RATE_LIMIT_VAL="$(fetch_ssm "$SSM_BRIEF_RATE_LIMIT" || true)"
  BRIEF_ICS_URLS_VAL="$(fetch_ssm "$SSM_BRIEF_ICS_URLS" || true)"
  _ssm_tg_id="$(fetch_ssm "$SSM_TELEGRAM_API_ID" || true)"
  _ssm_tg_hash="$(fetch_ssm "$SSM_TELEGRAM_API_HASH" || true)"
  TELEGRAM_SESSION_PATH_VAL="$(fetch_ssm "$SSM_TELEGRAM_SESSION_PATH" || true)"
  [[ -n "$BRIEF_API_KEY_VAL" ]] && BRIEF_SOURCE="ssm"
  if [[ -n "$_ssm_tg_id" && -n "$_ssm_tg_hash" ]]; then
    TELEGRAM_API_ID_VAL="$_ssm_tg_id"
    TELEGRAM_API_HASH_VAL="$_ssm_tg_hash"
    TELEGRAM_USER_API_SOURCE="ssm"
  fi
fi
if [[ -z "$BRIEF_API_KEY_VAL" && -n "$PRESERVE_BRIEF_API_KEY" ]]; then
  BRIEF_API_KEY_VAL="$PRESERVE_BRIEF_API_KEY"
  BRIEF_SOURCE="preserved"
fi
if [[ -z "$BRIEF_MAILBOXES_PATH_VAL" && -n "$PRESERVE_BRIEF_MAILBOXES_PATH" ]]; then
  BRIEF_MAILBOXES_PATH_VAL="$PRESERVE_BRIEF_MAILBOXES_PATH"
fi
if [[ -z "$BRIEF_RATE_LIMIT_VAL" && -n "$PRESERVE_BRIEF_RATE_LIMIT_PER_MINUTE" ]]; then
  BRIEF_RATE_LIMIT_VAL="$PRESERVE_BRIEF_RATE_LIMIT_PER_MINUTE"
fi
if [[ -z "$BRIEF_ICS_URLS_VAL" && -n "$PRESERVE_BRIEF_ICS_URLS" ]]; then
  BRIEF_ICS_URLS_VAL="$PRESERVE_BRIEF_ICS_URLS"
fi
if [[ -z "$TELEGRAM_API_ID_VAL" || -z "$TELEGRAM_API_HASH_VAL" ]]; then
  TELEGRAM_API_ID_VAL=""
  TELEGRAM_API_HASH_VAL=""
  TELEGRAM_USER_API_SOURCE="none"
  if [[ -n "$PRESERVE_TELEGRAM_API_ID" && -n "$PRESERVE_TELEGRAM_API_HASH" ]]; then
    TELEGRAM_API_ID_VAL="$PRESERVE_TELEGRAM_API_ID"
    TELEGRAM_API_HASH_VAL="$PRESERVE_TELEGRAM_API_HASH"
    TELEGRAM_USER_API_SOURCE="preserved"
  fi
fi
if [[ -z "$TELEGRAM_SESSION_PATH_VAL" && -n "$PRESERVE_TELEGRAM_SESSION_PATH" ]]; then
  TELEGRAM_SESSION_PATH_VAL="$PRESERVE_TELEGRAM_SESSION_PATH"
fi
if [[ -f "$ROOT_DIR/.env.aws" ]]; then
  if [[ -z "$BRIEF_API_KEY_VAL" ]]; then
    _v="$(_read_env_aws_key BRIEF_API_KEY)"
    if [[ -n "$_v" ]]; then
      BRIEF_API_KEY_VAL="$_v"
      BRIEF_SOURCE="env.aws"
    fi
  fi
  if [[ -z "$BRIEF_MAILBOXES_PATH_VAL" ]]; then
    _v="$(_read_env_aws_key BRIEF_MAILBOXES_PATH)"
    [[ -n "$_v" ]] && BRIEF_MAILBOXES_PATH_VAL="$_v"
  fi
  if [[ -z "$BRIEF_RATE_LIMIT_VAL" ]]; then
    _v="$(_read_env_aws_key BRIEF_RATE_LIMIT_PER_MINUTE)"
    [[ -n "$_v" ]] && BRIEF_RATE_LIMIT_VAL="$_v"
  fi
  if [[ -z "$BRIEF_ICS_URLS_VAL" ]]; then
    _v="$(_read_env_aws_key BRIEF_ICS_URLS)"
    [[ -n "$_v" ]] && BRIEF_ICS_URLS_VAL="$_v"
  fi
  if [[ -z "$TELEGRAM_API_ID_VAL" || -z "$TELEGRAM_API_HASH_VAL" ]]; then
    _env_tg_id="$(_read_env_aws_key TELEGRAM_API_ID)"
    _env_tg_hash="$(_read_env_aws_key TELEGRAM_API_HASH)"
    if [[ -n "$_env_tg_id" && -n "$_env_tg_hash" ]]; then
      TELEGRAM_API_ID_VAL="$_env_tg_id"
      TELEGRAM_API_HASH_VAL="$_env_tg_hash"
      TELEGRAM_USER_API_SOURCE="env.aws"
    else
      TELEGRAM_API_ID_VAL=""
      TELEGRAM_API_HASH_VAL=""
      TELEGRAM_USER_API_SOURCE="none"
    fi
  fi
  if [[ -z "$TELEGRAM_SESSION_PATH_VAL" ]]; then
    _v="$(_read_env_aws_key TELEGRAM_SESSION_PATH)"
    [[ -n "$_v" ]] && TELEGRAM_SESSION_PATH_VAL="$_v"
  fi
fi
[[ -z "$BRIEF_MAILBOXES_PATH_VAL" ]] && BRIEF_MAILBOXES_PATH_VAL="$BRIEF_MAILBOXES_PATH_DEFAULT"
[[ -z "$BRIEF_RATE_LIMIT_VAL" ]] && BRIEF_RATE_LIMIT_VAL="$BRIEF_RATE_LIMIT_DEFAULT"
[[ -z "$TELEGRAM_SESSION_PATH_VAL" ]] && TELEGRAM_SESSION_PATH_VAL="$TELEGRAM_SESSION_PATH_DEFAULT"

for _brief_key in \
  BRIEF_API_KEY \
  BRIEF_MAILBOXES_PATH \
  BRIEF_RATE_LIMIT_PER_MINUTE \
  BRIEF_ICS_URLS \
  TELEGRAM_API_ID \
  TELEGRAM_API_HASH \
  TELEGRAM_SESSION_PATH; do
  grep -q "^${_brief_key}=" "$RUNTIME_ENV" 2>/dev/null && sed -i "/^${_brief_key}=/d" "$RUNTIME_ENV"
done
[[ -n "$BRIEF_API_KEY_VAL" ]] && printf "BRIEF_API_KEY=%s\n" "$BRIEF_API_KEY_VAL" >> "$RUNTIME_ENV"
printf "BRIEF_MAILBOXES_PATH=%s\n" "$BRIEF_MAILBOXES_PATH_VAL" >> "$RUNTIME_ENV"
printf "BRIEF_RATE_LIMIT_PER_MINUTE=%s\n" "$BRIEF_RATE_LIMIT_VAL" >> "$RUNTIME_ENV"
[[ -n "$BRIEF_ICS_URLS_VAL" ]] && printf "BRIEF_ICS_URLS=%s\n" "$BRIEF_ICS_URLS_VAL" >> "$RUNTIME_ENV"
# Write Telethon pair together only (never one without the other).
if [[ -n "$TELEGRAM_API_ID_VAL" && -n "$TELEGRAM_API_HASH_VAL" ]]; then
  printf "TELEGRAM_API_ID=%s\n" "$TELEGRAM_API_ID_VAL" >> "$RUNTIME_ENV"
  printf "TELEGRAM_API_HASH=%s\n" "$TELEGRAM_API_HASH_VAL" >> "$RUNTIME_ENV"
fi
printf "TELEGRAM_SESSION_PATH=%s\n" "$TELEGRAM_SESSION_PATH_VAL" >> "$RUNTIME_ENV"

echo "Rendered (source=$SOURCE)"
echo "Present: TELEGRAM_BOT_TOKEN=YES TELEGRAM_CHAT_ID=YES ADMIN_ACTIONS_KEY=YES DIAGNOSTICS_API_KEY=$([[ -n "$DIAG_KEY" ]] && echo YES || echo NO) ATP_API_KEY=$([[ -n "$ATP_API_KEY" ]] && echo YES || echo NO) GITHUB_TOKEN=$([[ "$HAS_GITHUB_PAT" == "YES" ]] && echo YES || echo NO) GITHUB_APP=$GITHUB_APP_ALL GITHUB_AUTH_MODE=$GITHUB_AUTH_MODE ALLOW_LEGACY_GITHUB_PAT=$([[ "$GITHUB_AUTH_MODE" == "legacy_transition" ]] && echo YES || echo NO) NOTION_API_KEY=$([[ -n "$NOTION_API_KEY_VAL" ]] && echo YES || echo NO) NOTION_TASK_DB=$([[ -n "$NOTION_TASK_DB_VAL" ]] && echo YES || echo NO) EXCHANGE_CUSTOM=$([[ -n "$EXCHANGE_API_KEY_VAL" && -n "$EXCHANGE_API_SECRET_VAL" ]] && echo YES || echo NO) EXCHANGE_CUSTOM_SOURCE=$EXCHANGE_CREDS_SOURCE JARVIS_4B_PROPOSALS_ENABLED=$JARVIS_4B_PROPOSALS_ENABLED JARVIS_4B_SOURCE=$JARVIS_4B_SOURCE JARVIS_PHASE5_SOURCE=$JARVIS_PHASE5_SOURCE JARVIS_PATCH_APPLY_ENABLED=$JARVIS_PATCH_APPLY_ENABLED JARVIS_PR_CREATION_ENABLED=$JARVIS_PR_CREATION_ENABLED JARVIS_GITHUB_WRITE_ENABLED=$JARVIS_GITHUB_WRITE_ENABLED JARVIS_REQUIRE_DOUBLE_APPROVAL=$JARVIS_REQUIRE_DOUBLE_APPROVAL BRIEF_API_KEY=$([[ -n "$BRIEF_API_KEY_VAL" ]] && echo YES || echo NO) BRIEF_SOURCE=$BRIEF_SOURCE TELEGRAM_USER_API=$([[ -n "$TELEGRAM_API_ID_VAL" && -n "$TELEGRAM_API_HASH_VAL" ]] && echo YES || echo NO) TELEGRAM_USER_API_SOURCE=$TELEGRAM_USER_API_SOURCE"

# umask 077 writes 600 ubuntu:ubuntu; backend appuser (uid 10001) cannot read the
# bind-mounted file, so pydantic Settings()/Telegram refresh raises PermissionError.
# Match entrypoint: root:appuser 640 when docker is available; else chmod 640 for host.
chmod 640 "$RUNTIME_ENV" 2>/dev/null || true
if command -v docker >/dev/null 2>&1; then
  docker exec -u root automated-trading-platform-backend-aws-1 \
    sh -c 'chown root:appuser /app/secrets/runtime.env && chmod 640 /app/secrets/runtime.env' \
    >/dev/null 2>&1 || true
fi

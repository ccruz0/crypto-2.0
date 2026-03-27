#!/usr/bin/env bash
# Create a minimal secrets/runtime.env with ATP_API_KEY (generated) and placeholders.
# Use when you don't have SSM or .env.aws yet. Backend and market-updater can start;
# Telegram stays disabled until you add TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID.
#
# Usage (from repo root):
#   cd ~/crypto-2.0
#   ./scripts/aws/create_runtime_env.sh
#
# On EC2: run "git pull" first so this script exists; ensure .env or .env.aws exists for DATABASE_URL.
#
# If secrets/runtime.env already exists: preserves existing ATP_API_KEY if set,
# only generates a new one when missing.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
if [[ ! -f "$ROOT_DIR/docker-compose.yml" ]]; then
  echo "ERROR: repo root not found (docker-compose.yml missing)" >&2
  exit 1
fi

SECRETS_DIR="$ROOT_DIR/secrets"
RUNTIME_ENV="$SECRETS_DIR/runtime.env"
mkdir -p "$SECRETS_DIR"

# Ensure .env exists so docker compose does not complain (env_file: .env)
if [[ ! -f "$ROOT_DIR/.env" ]]; then
  if [[ -f "$ROOT_DIR/.env.example" ]]; then
    cp "$ROOT_DIR/.env.example" "$ROOT_DIR/.env"
    echo "Created .env from .env.example (edit for DATABASE_URL / POSTGRES_PASSWORD if needed)."
  else
    touch "$ROOT_DIR/.env"
    echo "Created empty .env; add DATABASE_URL and POSTGRES_PASSWORD for the db service."
  fi
fi

# Ensure .env.aws exists (compose references it; avoid "env file .env.aws not found")
if [[ ! -f "$ROOT_DIR/.env.aws" ]]; then
  if [[ -f "$ROOT_DIR/.env" ]]; then
    cp "$ROOT_DIR/.env" "$ROOT_DIR/.env.aws"
    echo "Created .env.aws from .env (compose env_file)."
  elif [[ -f "$ROOT_DIR/.env.example" ]]; then
    cp "$ROOT_DIR/.env.example" "$ROOT_DIR/.env.aws"
    echo "Created .env.aws from .env.example (edit for DATABASE_URL / POSTGRES_PASSWORD)."
  else
    touch "$ROOT_DIR/.env.aws"
    echo "Created empty .env.aws; add DATABASE_URL and POSTGRES_PASSWORD."
  fi
fi

# Preserve existing ATP_API_KEY if present
ATP_API_KEY=""
if [[ -f "$RUNTIME_ENV" ]]; then
  ATP_API_KEY="$(grep -E '^ATP_API_KEY=' "$RUNTIME_ENV" 2>/dev/null | cut -d= -f2- | sed 's/^["'\'']//;s/["'\'']$//' || true)"
fi

if [[ -z "$ATP_API_KEY" ]]; then
  if command -v python3 >/dev/null 2>&1; then
    ATP_API_KEY="$(python3 -c "import secrets; print(secrets.token_urlsafe(32))")"
  else
    echo "ERROR: python3 required to generate ATP_API_KEY" >&2
    exit 1
  fi
  echo "Generated new ATP_API_KEY (save it for x-api-key header and /api/health/repair):"
  echo "  ATP_API_KEY=$ATP_API_KEY"
  echo ""
fi

umask 077
{
  echo "# Minimal runtime.env — created by scripts/aws/create_runtime_env.sh"
  echo "# Do NOT commit. Add TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID for Telegram; re-run render_runtime_env.sh when using SSM."
  echo "ATP_API_KEY=$ATP_API_KEY"
  echo "ENVIRONMENT=aws"
  echo "RUN_TELEGRAM=false"
  echo "TELEGRAM_BOT_TOKEN="
  echo "TELEGRAM_CHAT_ID="
  echo "ADMIN_ACTIONS_KEY="
  echo "DIAGNOSTICS_API_KEY="
} > "$RUNTIME_ENV"

echo "Created: $RUNTIME_ENV"
# Redacted DB URL (host and db name only, no credentials)
if [[ -f "$ROOT_DIR/.env" ]]; then
  DB_URL_REDACTED="$(grep -E '^DATABASE_URL=' "$ROOT_DIR/.env" 2>/dev/null | sed -E 's|://[^:]+:[^@]+@|://***:***@|; s|/[^/?]+(\?|$)|/***\1|' || true)"
  [[ -n "$DB_URL_REDACTED" ]] && echo "DATABASE_URL (redacted): ${DB_URL_REDACTED}"
fi
echo "Next: run scripts/db/bootstrap.sh if watchlist_items is missing; then restart stack (docker compose --profile aws up -d)."
echo "  curl -H \"x-api-key: \$ATP_API_KEY\" -X POST http://127.0.0.1:8002/api/engine/run-once"
echo "  curl -H \"x-api-key: \$ATP_API_KEY\" -X POST http://127.0.0.1:8002/api/health/repair"

#!/usr/bin/env bash
# Inventory required runtime env vars for ATP AWS profile (post-compromise rebuild).
# Run from repo root. Output: table of ENV var, Purpose, Where used, Rotate?, How to obtain.
set -uo pipefail

REPO_ROOT="${1:-.}"
cd "$REPO_ROOT" || exit 1
ROOT="$(pwd)"

echo "=== ATP required env vars (AWS profile) ==="
echo ""

# Scan docker-compose for env_file and ${VAR} references
COMPOSE_VARS=""
for f in docker-compose.yml; do
  [ -f "$f" ] && COMPOSE_VARS="$COMPOSE_VARS $(grep -oE '\$\{[A-Z][A-Z0-9_]*\}' "$f" 2>/dev/null | sed 's/\${//;s/:-.*//;s/}//' | tr ' ' '\n' | sort -u)"
done
COMPOSE_VARS="$(echo "$COMPOSE_VARS" | tr ' \n' '\n' | sort -u | grep -v '^$' || true)"

# Known AWS-required vars with metadata (Purpose, Rotate, How)
# Format: VAR|Purpose|Where|Rotate|How
KNOWN="
POSTGRES_DB|Database name|docker-compose.yml db, aws-backup|YES|__REUSE_OR_NEW__ (e.g. atp)
POSTGRES_USER|Database user|docker-compose.yml db, aws-backup|YES|__REUSE_OR_NEW__ (e.g. trader)
POSTGRES_PASSWORD|Database password|docker-compose.yml db, aws-backup; never inline|YES|__GENERATE__
DATABASE_URL|PostgreSQL connection string|backend, market-updater, backend-aws|YES|Build from POSTGRES_USER/PASSWORD/POSTGRES_DB and host db:5432
SECRET_KEY|App signing/session secret|backend/app/core/config.py, main.py|YES|__GENERATE__
DIAGNOSTICS_API_KEY|Gate /api/diagnostics + monitoring|routes_monitoring, routes_diag|YES|__GENERATE__
ADMIN_ACTIONS_KEY|X-Admin-Key admin/dangerous actions|routes_admin, routes_portfolio, main|YES|__GENERATE__
# Deprecated: TELEGRAM_BOT_TOKEN (plaintext) not supported; use TELEGRAM_BOT_TOKEN_ENCRYPTED + TELEGRAM_KEY_FILE.
TELEGRAM_BOT_TOKEN_ENCRYPTED|Telegram bot token encrypted (AWS)|telegram_secrets, render_runtime_env|YES|scripts/setup_telegram_token.py
TELEGRAM_CHAT_ID|Telegram chat/channel ID (AWS)|main, telegram_notifier, render_runtime_env|NO*|__REUSE_ID__
TELEGRAM_CHAT_ID_AWS|Canonical AWS chat ID|telegram_notifier, routes_control, health|NO*|__REUSE_ID__
TELEGRAM_ALERT_BOT_TOKEN|Alertmanager→Telegram webhook bot|telegram-alerts/server.py|YES|__FROM_BOTFATHER__
TELEGRAM_ALERT_CHAT_ID|Alertmanager→Telegram chat|telegram-alerts/server.py|NO*|__REUSE_ID__
EXCHANGE_CUSTOM_API_KEY|Crypto.com Exchange API key|routes_internal, crypto_com_trade, scripts|YES|__ROTATE_IN_EXCHANGE__
EXCHANGE_CUSTOM_API_SECRET|Crypto.com Exchange API secret|routes_internal, crypto_com_trade, scripts|YES|__ROTATE_IN_EXCHANGE__
EXCHANGE_CUSTOM_BASE_URL|Crypto.com API base URL|backend override|NO|https://api.crypto.com/exchange/v1
CRYPTO_REST_BASE|Crypto REST base (alias)|backend|NO|https://api.crypto.com/exchange/v1
API_BASE_URL|Backend URL (internal)|compose backend-aws|NO|http://backend-aws:8002
FRONTEND_URL|Frontend URL CORS/links|core/environment.py|NO|Public URL e.g. https://...
NEXT_PUBLIC_API_URL|Frontend API base (build-time)|frontend environment.ts|NO|/api
NEXT_PUBLIC_ENVIRONMENT|Frontend env label (build-time)|frontend|NO|aws
GRAFANA_ADMIN_USER|Grafana admin username|compose grafana|YES|__REUSE_OR_NEW__
GF_SECURITY_ADMIN_PASSWORD|Grafana admin password|Grafana env_file|YES|__GENERATE__
ENVIRONMENT|Environment identifier|backend config|NO|aws
APP_ENV|App environment (aws/local)|backend, telegram routing|NO|aws
RUN_TELEGRAM|Enable Telegram sending|compose, main|NO|true
RUNTIME_ORIGIN|Runtime origin (AWS/LOCAL)|backend config, guards|NO|AWS
LIVE_TRADING|Trading enabled flag|routes_control, live_trading|NO|true
USE_CRYPTO_PROXY|Use crypto proxy (AWS: false)|compose|NO|false
AWS_INSTANCE_IP|Optional instance IP for diag|backend scripts|NO|New EC2 public IP
"

# Print table header
printf "%-30s | %-26s | %-36s | %-4s | %s\n" "ENV VAR" "PURPOSE" "WHERE USED" "ROTATE" "HOW TO OBTAIN"
printf "%-30s-+-%-26s-+-%-36s-+-%-4s-+-%s\n" "------------------------------" "--------------------------" "------------------------------------" "----" "-------------------"

echo "$KNOWN" | grep -v '^$' | while IFS='|' read -r var purpose where rotate how; do
  # trim leading/trailing space from each field
  var="$(echo "$var" | xargs)"; purpose="$(echo "$purpose" | xargs)"; where="$(echo "$where" | xargs)"; rotate="$(echo "$rotate" | xargs)"; how="$(echo "$how" | xargs)"
  printf "%-30s | %-26s | %-36s | %-4s | %s\n" "$var" "$purpose" "$where" "$rotate" "$how"
done

echo ""
echo "(*) ROTATE=NO for identifiers (e.g. TELEGRAM_CHAT_ID): reuse same ID; rotate the token/secret."
echo ""

# Optional: list any ${VAR} from compose not in KNOWN
echo "=== Other \${VAR} referenced in docker-compose (may have defaults) ==="
echo "$COMPOSE_VARS" | while read -r v; do
  [[ -z "$v" ]] && continue
  case "$v" in
    POSTGRES_DB|POSTGRES_USER|GRAFANA_ADMIN_USER|FRONTEND_URL|NEXT_PUBLIC_ENVIRONMENT) ;;
    *) echo "$KNOWN" | grep -q "^${v}|" || echo "  $v" ;;
  esac
done

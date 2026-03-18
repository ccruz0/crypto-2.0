#!/usr/bin/env bash
# Diagnose NOTION_API_KEY and NOTION_TASK_DB: presence and source.
# Does not print or expose secret values. Safe to run on LAB or locally.
#
# Usage: ./scripts/diagnostics/check_notion_env.sh
#        From repo root or any subdir (script finds repo root).

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
RUNTIME_ENV="${REPO_ROOT}/secrets/runtime.env"
ENV_AWS="${REPO_ROOT}/.env.aws"
REGION="${AWS_REGION:-${AWS_DEFAULT_REGION:-ap-southeast-1}}"

SSM_PROD_KEY="/automated-trading-platform/prod/notion/api_key"
SSM_PROD_DB="/automated-trading-platform/prod/notion/task_db"
SSM_LAB_KEY="/automated-trading-platform/lab/notion/api_key"

_report() {
  local var_name="$1"
  local status="$2"
  local source="$3"
  echo "  ${var_name}: ${status} (source: ${source})"
}

# --- SSM (prod + lab) ---
NOTION_KEY_SSM=""
NOTION_DB_SSM=""
if command -v aws >/dev/null 2>&1 && aws sts get-caller-identity >/dev/null 2>&1; then
  NOTION_KEY_SSM="$(aws ssm get-parameter --name "$SSM_PROD_KEY" --with-decryption --query Parameter.Value --output text --region "$REGION" 2>/dev/null)" || true
  [[ -z "$NOTION_KEY_SSM" ]] && NOTION_KEY_SSM="$(aws ssm get-parameter --name "$SSM_LAB_KEY" --with-decryption --query Parameter.Value --output text --region "$REGION" 2>/dev/null)" || true
  NOTION_DB_SSM="$(aws ssm get-parameter --name "$SSM_PROD_DB" --with-decryption --query Parameter.Value --output text --region "$REGION" 2>/dev/null)" || true
fi

# --- .env.aws ---
NOTION_KEY_ENV_AWS=""
NOTION_DB_ENV_AWS=""
if [[ -f "$ENV_AWS" ]]; then
  NOTION_KEY_ENV_AWS="$(grep -E '^NOTION_API_KEY=' "$ENV_AWS" 2>/dev/null | cut -d= -f2- | tr -d '\r' || true)"
  NOTION_DB_ENV_AWS="$(grep -E '^NOTION_TASK_DB=' "$ENV_AWS" 2>/dev/null | cut -d= -f2- | tr -d '\r' || true)"
fi

# --- runtime.env ---
NOTION_KEY_RUNTIME=""
NOTION_DB_RUNTIME=""
if [[ -f "$RUNTIME_ENV" ]]; then
  NOTION_KEY_RUNTIME="$(grep -E '^NOTION_API_KEY=' "$RUNTIME_ENV" 2>/dev/null | cut -d= -f2- | tr -d '\r' || true)"
  NOTION_DB_RUNTIME="$(grep -E '^NOTION_TASK_DB=' "$RUNTIME_ENV" 2>/dev/null | cut -d= -f2- | tr -d '\r' || true)"
fi

# --- Container (if docker compose available and backend-aws up) ---
NOTION_KEY_CONTAINER=""
NOTION_DB_CONTAINER=""
if command -v docker >/dev/null 2>&1; then
  if docker compose --profile aws ps backend-aws 2>/dev/null | grep -q Up; then
    NOTION_KEY_CONTAINER="$(docker compose --profile aws exec -T backend-aws printenv NOTION_API_KEY 2>/dev/null)" || true
    NOTION_DB_CONTAINER="$(docker compose --profile aws exec -T backend-aws printenv NOTION_TASK_DB 2>/dev/null)" || true
  fi
fi

# Resolve effective source for each
key_source="missing"
db_source="missing"
key_ok=false
db_ok=false

if [[ -n "$NOTION_KEY_CONTAINER" ]]; then key_source="container"; key_ok=true; fi
if [[ -n "$NOTION_KEY_RUNTIME" && "$key_source" == "missing" ]]; then key_source="runtime.env"; key_ok=true; fi
if [[ -n "$NOTION_KEY_ENV_AWS" && "$key_source" == "missing" ]]; then key_source=".env.aws"; key_ok=true; fi
if [[ -n "$NOTION_KEY_SSM" ]]; then key_source="SSM"; key_ok=true; fi

if [[ -n "$NOTION_DB_CONTAINER" ]]; then db_source="container"; db_ok=true; fi
if [[ -n "$NOTION_DB_RUNTIME" && "$db_source" == "missing" ]]; then db_source="runtime.env"; db_ok=true; fi
if [[ -n "$NOTION_DB_ENV_AWS" && "$db_source" == "missing" ]]; then db_source=".env.aws"; db_ok=true; fi
if [[ -n "$NOTION_DB_SSM" ]]; then db_source="SSM"; db_ok=true; fi

echo "NOTION env diagnostics (no secrets printed)"
echo "  Repo root: $REPO_ROOT"
echo "  runtime.env: $RUNTIME_ENV ($([[ -f "$RUNTIME_ENV" ]] && echo present || echo missing))"
echo "  .env.aws: $ENV_AWS ($([[ -f "$ENV_AWS" ]] && echo present || echo missing))"
echo ""
_report "NOTION_API_KEY" "$([[ "$key_ok" == true ]] && echo present || echo missing)" "$key_source"
_report "NOTION_TASK_DB"  "$([[ "$db_ok" == true ]] && echo present || echo missing)"  "$db_source"
echo ""

if [[ "$key_ok" != true || "$db_ok" != true ]]; then
  echo "Recommendation: run scripts/aws/fix_notion_env_lab.sh (on LAB) or ensure SSM parameter exists and re-run render_runtime_env.sh"
  exit 1
fi
exit 0

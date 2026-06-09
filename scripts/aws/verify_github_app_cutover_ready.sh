#!/usr/bin/env bash
# Verify GitHub App cutover readiness. Never prints secret values.
#
# Checks:
#   1. SSM github_app/* parameter existence and type (if AWS CLI available)
#   2. Local secrets/runtime.env key presence
#   3. Backend container env presence (via scripts/verify_deploy_secrets.sh)
#   4. Live in-container token mint (app.services.github_app_auth.get_github_api_token)
#
# Final line: CUTOVER_READY=YES only when auth_mode is github_app AND a live
# installation token mint succeeds (auth_method == "github_app" and a token is
# returned). Presence of GITHUB_APP_* env vars alone is NOT sufficient.
# Exit code 0 in all evaluated states (legacy_transition is a valid, safe state).

set -euo pipefail
set +x 2>/dev/null || true

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$ROOT_DIR"

AWS_REGION="${AWS_REGION:-ap-southeast-1}"
SSM_PREFIX="/automated-trading-platform/prod/github_app"

echo "== 1. SSM parameter existence (names/types only) =="
if command -v aws >/dev/null 2>&1 && aws sts get-caller-identity >/dev/null 2>&1; then
  for p in app_id installation_id private_key_b64; do
    name="$SSM_PREFIX/$p"
    type="$(aws ssm describe-parameters \
      --region "$AWS_REGION" \
      --parameter-filters "Key=Name,Values=$name" \
      --query 'Parameters[0].Type' --output text 2>/dev/null || true)"
    if [[ -n "$type" && "$type" != "None" ]]; then
      echo "  $name: present (type=$type)"
    else
      echo "  $name: MISSING"
    fi
  done
else
  echo "  (skipped — AWS CLI or credentials unavailable)"
fi

echo
echo "== 2. Local secrets/runtime.env key presence =="
if [[ -f secrets/runtime.env ]]; then
  for key in GITHUB_APP_ID GITHUB_APP_INSTALLATION_ID GITHUB_APP_PRIVATE_KEY_B64 GITHUB_TOKEN ALLOW_LEGACY_GITHUB_PAT; do
    if sudo grep -q "^${key}=" secrets/runtime.env 2>/dev/null || grep -q "^${key}=" secrets/runtime.env 2>/dev/null; then
      echo "  $key: present"
    else
      echo "  $key: absent"
    fi
  done
else
  echo "  secrets/runtime.env not found (run scripts/aws/render_runtime_env.sh)"
fi

echo
echo "== 3. Container env (scripts/verify_deploy_secrets.sh) =="
AUTH_MODE="unknown"
VERIFY_OUT=""
if VERIFY_OUT="$(./scripts/verify_deploy_secrets.sh 2>&1)"; then
  :
else
  echo "  (verify_deploy_secrets.sh exited non-zero — backend may not be running)"
fi
echo "$VERIFY_OUT" | sed 's/^/  /'
AUTH_MODE="$(echo "$VERIFY_OUT" | sed -n 's/^[[:space:]]*auth_mode:[[:space:]]*//p' | head -1)"
[[ -z "$AUTH_MODE" ]] && AUTH_MODE="unknown"

# Locate the backend container for the live mint smoke. Prefer the exact
# compose service (avoids matching backend-aws-canary); fall back to name filters.
find_backend_container() {
  local cid=""
  cid="$(docker compose --profile aws ps -q backend-aws 2>/dev/null | head -1 || true)"
  if [[ -z "$cid" ]]; then
    cid="$(docker ps --filter 'name=backend-aws' --format '{{.ID}} {{.Names}}' 2>/dev/null \
      | awk '$2 !~ /canary/ {print $1; exit}' || true)"
  fi
  [[ -z "$cid" ]] && cid="$(docker ps -q --filter 'name=automated-trading-platform-backend' 2>/dev/null | head -1 || true)"
  [[ -z "$cid" ]] && cid="$(docker ps -q --filter 'name=backend-dev' 2>/dev/null | head -1 || true)"
  echo "$cid"
}

# Live token mint smoke (never prints tokens). Sets MINT_AUTH_METHOD / MINT_TOKEN_PRESENT.
MINT_AUTH_METHOD="unknown"
MINT_TOKEN_PRESENT="false"
run_live_mint_smoke() {
  local cid out
  cid="$(find_backend_container)"
  if [[ -z "$cid" ]]; then
    echo "  (live mint skipped — no backend container running)"
    return 1
  fi
  echo "  Using container: $(docker ps --filter "id=$cid" --format '{{.Names}}')"
  if ! out="$(docker exec -i "$cid" python3 - <<'PY' 2>&1
from app.services.github_app_auth import get_github_api_token
token, method = get_github_api_token()
print(f"auth_method={method}")
print(f"token_present={'true' if bool(token) else 'false'}")
PY
)"; then
    echo "  (live mint smoke failed to execute)"
    return 1
  fi
  echo "$out" | grep -E '^(auth_method|token_present)=' | sed 's/^/  /'
  MINT_AUTH_METHOD="$(echo "$out" | sed -n 's/^auth_method=//p' | head -1)"
  MINT_TOKEN_PRESENT="$(echo "$out" | sed -n 's/^token_present=//p' | head -1)"
  return 0
}

echo
echo "== Final status =="
echo "auth_mode: $AUTH_MODE"
case "$AUTH_MODE" in
  github_app)
    echo
    echo "== 4. Live GitHub App token mint smoke (no token printed) =="
    run_live_mint_smoke || true
    if [[ "$MINT_AUTH_METHOD" == "github_app" && "$MINT_TOKEN_PRESENT" == "true" ]]; then
      echo "Live token mint succeeded (auth_method=github_app, token_present=true)."
      echo "CUTOVER_READY=YES"
    else
      echo "NO-GO: GitHub App vars present but live token mint failed."
      echo "CUTOVER_READY=NO"
    fi
    ;;
  legacy_transition)
    echo "Transition mode active. Safe, but GitHub App cutover not complete."
    echo "CUTOVER_READY=NO"
    ;;
  none)
    echo "NO-GO: GitHub auth unavailable."
    echo "CUTOVER_READY=NO"
    ;;
  *)
    echo "Could not determine auth_mode (backend not running or verify script failed)."
    echo "CUTOVER_READY=NO"
    ;;
esac

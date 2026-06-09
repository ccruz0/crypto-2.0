#!/usr/bin/env bash
# Verify GitHub App cutover readiness. Presence-only checks; never prints secret values.
#
# Checks:
#   1. SSM github_app/* parameter existence and type (if AWS CLI available)
#   2. Local secrets/runtime.env key presence
#   3. Backend container env presence (via scripts/verify_deploy_secrets.sh)
#
# Final line: CUTOVER_READY=YES only when auth_mode is github_app.
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

echo
echo "== Final status =="
echo "auth_mode: $AUTH_MODE"
case "$AUTH_MODE" in
  github_app)
    echo "CUTOVER_READY=YES"
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

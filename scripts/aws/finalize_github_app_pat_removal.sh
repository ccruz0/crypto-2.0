#!/usr/bin/env bash
# Finalize GitHub App cutover by removing legacy PAT from SSM and local env files.
# Safe by default — requires explicit confirmation and pre-flight checks.
# Never prints secret values.
#
# Usage (after observation window, all checks green):
#   CONFIRM_REMOVE_LEGACY_PAT=yes bash scripts/aws/finalize_github_app_pat_removal.sh
#
# Before recommended window (2026-06-12 08:18 UTC), also set:
#   OVERRIDE_EARLY_PAT_REMOVAL=yes

set -euo pipefail
set +x 2>/dev/null || true

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$ROOT_DIR"

AWS_REGION="${AWS_REGION:-ap-southeast-1}"
SSM_GITHUB_TOKEN="/automated-trading-platform/prod/github_token"
RECOMMENDED_PAT_REMOVAL_UTC="2026-06-12 08:18:00"
HEALTH_TIMEOUT_S="${HEALTH_TIMEOUT_S:-120}"
PING_URL="http://127.0.0.1:8002/ping_fast"
READY_URL="http://127.0.0.1:8002/api/health/ready"
CANARY_PING_URL="http://127.0.0.1:8003/ping_fast"
CANARY_READY_URL="http://127.0.0.1:8003/api/health/ready"

fail() {
  echo "ERROR: $*" >&2
  exit 1
}

print_rollback() {
  cat <<'EOF'

== Rollback (if GitHub App becomes unavailable) ==

1. Restore legacy PAT to SSM (use your stored PAT value — not printed here):
   export AWS_REGION=ap-southeast-1
   aws ssm put-parameter \
     --region "$AWS_REGION" \
     --name /automated-trading-platform/prod/github_token \
     --value "$YOUR_LEGACY_PAT" \
     --type SecureString \
     --overwrite

2. Re-render runtime env and recreate backends:
   cd /home/ubuntu/crypto-2.0
   bash scripts/aws/render_runtime_env.sh
   sudo chown 10001:10001 secrets/runtime.env
   sudo chmod 600 secrets/runtime.env
   sudo docker compose --profile aws up -d --force-recreate backend-aws backend-aws-canary

3. Temporarily enable legacy transition only if GitHub App is unavailable:
   # Add ALLOW_LEGACY_GITHUB_PAT=true to secrets/runtime.env via render after SSM restore,
   # or use: bash scripts/aws/render_and_recreate_backend_safe.sh
   # Expected: auth_mode: legacy_transition

4. Verify:
   bash scripts/aws/verify_github_app_cutover_ready.sh
   ./scripts/verify_deploy_secrets.sh

EOF
}

container_env_present() {
  local service="$1"
  local key="$2"
  local cid

  cid="$(docker compose --profile aws ps -q "$service" 2>/dev/null | head -1 || true)"
  [[ -z "$cid" ]] && return 2
  docker exec -i "$cid" python3 -c "import os; print('yes' if bool((os.getenv('${key}') or '').strip()) else 'no')" 2>/dev/null
}

service_healthy() {
  local service="$1"
  local cid health

  cid="$(docker compose --profile aws ps -q "$service" 2>/dev/null | head -1 || true)"
  [[ -z "$cid" ]] && return 1
  health="$(docker inspect "$cid" --format='{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' 2>/dev/null || echo unknown)"
  [[ "$health" == "healthy" ]]
}

wait_both_backends_healthy() {
  local deadline ping_status ready_status canary_ping canary_ready

  deadline=$(( $(date +%s) + HEALTH_TIMEOUT_S ))
  while (( $(date +%s) < deadline )); do
    ping_status="$(curl -s -m 5 "$PING_URL" 2>/dev/null || true)"
    ready_status="$(curl -s -m 10 "$READY_URL" 2>/dev/null || true)"
    canary_ping="$(curl -s -m 5 "$CANARY_PING_URL" 2>/dev/null || true)"
    canary_ready="$(curl -s -m 10 "$CANARY_READY_URL" 2>/dev/null || true)"

    if echo "$ping_status" | grep -q '"status"[[:space:]]*:[[:space:]]*"ok"' \
       && echo "$ready_status" | grep -q '"status"[[:space:]]*:[[:space:]]*"ready"' \
       && echo "$canary_ping" | grep -q '"status"[[:space:]]*:[[:space:]]*"ok"' \
       && echo "$canary_ready" | grep -q '"status"[[:space:]]*:[[:space:]]*"ready"'; then
      echo "  backend-aws and backend-aws-canary: healthy"
      return 0
    fi
    sleep 5
  done
  return 1
}

echo "== GitHub App legacy PAT removal (guarded) =="
echo "repo: $ROOT_DIR"
echo "time_utc: $(date -u '+%Y-%m-%d %H:%M:%S UTC')"
echo

if [[ "${CONFIRM_REMOVE_LEGACY_PAT:-}" != "yes" ]]; then
  fail "Refusing to run without CONFIRM_REMOVE_LEGACY_PAT=yes"
fi

now_epoch="$(date -u +%s)"
recommended_epoch="$(date -u -d "$RECOMMENDED_PAT_REMOVAL_UTC" +%s 2>/dev/null || date -u -j -f '%Y-%m-%d %H:%M:%S' "$RECOMMENDED_PAT_REMOVAL_UTC" +%s 2>/dev/null || echo 0)"
if [[ "$recommended_epoch" -gt 0 && "$now_epoch" -lt "$recommended_epoch" ]]; then
  echo "WARNING: Current UTC time is before recommended PAT removal ($RECOMMENDED_PAT_REMOVAL_UTC UTC)."
  echo "         Cutover observation window may be incomplete."
  if [[ "${OVERRIDE_EARLY_PAT_REMOVAL:-}" != "yes" ]]; then
    fail "Refusing early PAT removal without OVERRIDE_EARLY_PAT_REMOVAL=yes"
  fi
  echo "  OVERRIDE_EARLY_PAT_REMOVAL=yes — proceeding despite early window."
fi
echo

echo "== Pre-flight checks =="

service_healthy backend-aws || fail "backend-aws is not healthy"
echo "  backend-aws: healthy"

service_healthy backend-aws-canary || fail "backend-aws-canary is not healthy"
echo "  backend-aws-canary: healthy"

VERIFY_OUT=""
VERIFY_OUT="$(bash scripts/aws/verify_github_app_cutover_ready.sh 2>&1)" || true
AUTH_MODE="$(echo "$VERIFY_OUT" | sed -n 's/^auth_mode:[[:space:]]*//p' | head -1)"
CUTOVER_READY="$(echo "$VERIFY_OUT" | sed -n 's/^CUTOVER_READY=//p' | head -1)"

[[ "$AUTH_MODE" == "github_app" ]] || fail "auth_mode is not github_app (got ${AUTH_MODE:-unknown})"
echo "  auth_mode: github_app"

[[ "$CUTOVER_READY" == "YES" ]] || fail "CUTOVER_READY is not YES (got ${CUTOVER_READY:-unknown})"
echo "  CUTOVER_READY: YES"

if ! echo "$VERIFY_OUT" | grep -q 'Live token mint succeeded'; then
  fail "live token mint not confirmed"
fi
echo "  live token mint: OK"
echo

echo "== 1. Delete SSM legacy PAT parameter =="
echo "  parameter: $SSM_GITHUB_TOKEN"
if command -v aws >/dev/null 2>&1 && aws sts get-caller-identity >/dev/null 2>&1; then
  if aws ssm describe-parameters \
      --region "$AWS_REGION" \
      --parameter-filters "Key=Name,Values=$SSM_GITHUB_TOKEN" \
      --query 'Parameters[0].Name' --output text 2>/dev/null | grep -q "$SSM_GITHUB_TOKEN"; then
    aws ssm delete-parameter --region "$AWS_REGION" --name "$SSM_GITHUB_TOKEN"
    echo "  deleted: $SSM_GITHUB_TOKEN"
  else
    echo "  already absent: $SSM_GITHUB_TOKEN"
  fi
else
  fail "AWS CLI or credentials unavailable — cannot delete SSM parameter safely"
fi
echo

echo "== 2. Remove GITHUB_TOKEN= from local env files (if present) =="
for f in .env.aws secrets/runtime.env; do
  if [[ -f "$f" ]] && grep -q '^GITHUB_TOKEN=' "$f" 2>/dev/null; then
    sudo sed -i '/^GITHUB_TOKEN=/d' "$f" 2>/dev/null || sed -i '/^GITHUB_TOKEN=/d' "$f"
    echo "  removed GITHUB_TOKEN= line from $f"
  else
    echo "  $f: no GITHUB_TOKEN= line (unchanged)"
  fi
done
echo

echo "== 3. Re-render runtime env and recreate backends =="
sudo bash scripts/aws/render_runtime_env.sh
sudo chown 10001:10001 secrets/runtime.env
sudo chmod 600 secrets/runtime.env
sudo docker compose --profile aws up -d --force-recreate backend-aws backend-aws-canary
echo

echo "== 4. Wait for backends healthy (up to ${HEALTH_TIMEOUT_S}s) =="
wait_both_backends_healthy || {
  echo "ERROR: backends did not become healthy within ${HEALTH_TIMEOUT_S}s" >&2
  print_rollback
  exit 1
}
echo

echo "== 5. Post-removal verification =="
POST_VERIFY="$(bash scripts/aws/verify_github_app_cutover_ready.sh 2>&1)" || true
echo "$POST_VERIFY" | sed 's/^/  /'

POST_AUTH_MODE="$(echo "$POST_VERIFY" | sed -n 's/^auth_mode:[[:space:]]*//p' | head -1)"
POST_CUTOVER="$(echo "$POST_VERIFY" | sed -n 's/^CUTOVER_READY=//p' | head -1)"

verification_failed=no
[[ "$POST_AUTH_MODE" == "github_app" ]] || verification_failed=yes
[[ "$POST_CUTOVER" == "YES" ]] || verification_failed=yes

for svc in backend-aws backend-aws-canary; do
  present="$(container_env_present "$svc" GITHUB_TOKEN || echo error)"
  if [[ "$present" == "yes" ]]; then
    echo "  $svc GITHUB_TOKEN: present (unexpected)"
    verification_failed=yes
  elif [[ "$present" == "no" ]]; then
    echo "  $svc GITHUB_TOKEN: absent (expected)"
  else
    echo "  $svc GITHUB_TOKEN: could not verify"
    verification_failed=yes
  fi
done

echo
if [[ "$verification_failed" == "yes" ]]; then
  echo "POST-REMOVAL VERIFICATION FAILED"
  print_rollback
  exit 1
fi

echo "== Final =="
echo "auth_mode: github_app"
echo "CUTOVER_READY=YES"
echo "GITHUB_TOKEN absent from backend-aws and backend-aws-canary"
echo "Legacy PAT removal complete."

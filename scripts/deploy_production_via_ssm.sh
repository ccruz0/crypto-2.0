#!/usr/bin/env bash
# Deploy production via AWS SSM (no SSH required).
#
# Use when: SSH to PROD times out or is disabled; SSM PingStatus is Online.
#
# Steps: git pull on server, rebuild backend-aws (optional), restart backend-aws,
#        optional health check. Uses existing AWS CLI configuration.
#
# Usage:
#   ./scripts/deploy_production_via_ssm.sh
#   SKIP_REBUILD=1 ./scripts/deploy_production_via_ssm.sh   # pull + restart only (faster)
#   NO_CACHE=1 ./scripts/deploy_production_via_ssm.sh        # force --no-cache rebuild (fix stale /task)
#
# Requires: AWS CLI, SSM agent on PROD (PingStatus Online).

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

INSTANCE_ID="${ATP_INSTANCE_ID:-i-087953603011543c5}"
REGION="${AWS_REGION:-ap-southeast-1}"
SKIP_REBUILD="${SKIP_REBUILD:-0}"
NO_CACHE="${NO_CACHE:-0}"
export AWS_REGION="$REGION"

echo "=== Deploy PROD via SSM (instance $INSTANCE_ID) ==="
echo "  SKIP_REBUILD=$SKIP_REBUILD NO_CACHE=$NO_CACHE"
echo ""

# Check SSM
STATUS=$(aws ssm describe-instance-information --region "$REGION" \
  --filters "Key=InstanceIds,Values=$INSTANCE_ID" \
  --query 'InstanceInformationList[0].PingStatus' --output text 2>/dev/null || echo "NotFound")
[[ -z "$STATUS" || "$STATUS" == "None" ]] && STATUS="NotFound"

if [[ "$STATUS" != "Online" ]]; then
  echo "SSM PingStatus: $STATUS. PROD must be Online for SSM deploy."
  echo "Run: ./scripts/aws/prod_reachability.sh"
  echo "See: docs/runbooks/PROD_DEPLOY_WHEN_SSH_FAILS.md"
  exit 1
fi

# Git pull fix: SSM runs without HOME; repo may have dubious ownership. Ensure git works.
GIT_PULL_PREFIX='export HOME=/home/ubuntu; git config --global --add safe.directory /home/ubuntu/automated-trading-platform 2>/dev/null || true; git config --global --add safe.directory /home/ubuntu/crypto-2.0 2>/dev/null || true; '
# Commands as JSON array (SSM RunShellScript runs them in sequence). Path: same as fix_telegram_anomalies_via_ssm.sh
if [[ "$SKIP_REBUILD" == "1" ]]; then
  PARAMS='commands=["set -e","cd /home/ubuntu/automated-trading-platform 2>/dev/null || cd /home/ubuntu/crypto-2.0 || exit 1","'"$GIT_PULL_PREFIX"'git fetch origin main && git reset --hard origin/main 2>/dev/null || git pull origin main 2>/dev/null || true","docker compose --profile aws up -d backend-aws","sleep 5","docker compose --profile aws ps backend-aws","curl -sS -o /dev/null -w \"%{http_code}\" --connect-timeout 5 http://localhost:8002/api/health || echo 000"]'
elif [[ "$NO_CACHE" == "1" ]]; then
  PARAMS='commands=["set -e","cd /home/ubuntu/automated-trading-platform 2>/dev/null || cd /home/ubuntu/crypto-2.0 || exit 1","'"$GIT_PULL_PREFIX"'git fetch origin main && git reset --hard origin/main 2>/dev/null || git pull origin main 2>/dev/null || true","docker compose --profile aws build --no-cache backend-aws 2>/dev/null || true","docker compose --profile aws up -d backend-aws","sleep 5","docker compose --profile aws ps backend-aws","curl -sS -o /dev/null -w \"%{http_code}\" --connect-timeout 5 http://localhost:8002/api/health || echo 000"]'
else
  PARAMS='commands=["set -e","cd /home/ubuntu/automated-trading-platform 2>/dev/null || cd /home/ubuntu/crypto-2.0 || exit 1","'"$GIT_PULL_PREFIX"'git fetch origin main && git reset --hard origin/main 2>/dev/null || git pull origin main 2>/dev/null || true","docker compose --profile aws build backend-aws 2>/dev/null || true","docker compose --profile aws up -d backend-aws","sleep 5","docker compose --profile aws ps backend-aws","curl -sS -o /dev/null -w \"%{http_code}\" --connect-timeout 5 http://localhost:8002/api/health || echo 000"]'
fi

COMMAND_ID=$(aws ssm send-command \
  --instance-ids "$INSTANCE_ID" \
  --region "$REGION" \
  --document-name "AWS-RunShellScript" \
  --parameters "$PARAMS" \
  --timeout-seconds 600 \
  --query 'Command.CommandId' --output text 2>&1)

if [[ -z "$COMMAND_ID" || "$COMMAND_ID" == Error* ]]; then
  echo "SSM send-command failed: $COMMAND_ID"
  exit 1
fi

echo "Command ID: $COMMAND_ID (waiting up to ~120s)..."
for i in $(seq 1 120); do
  S=$(aws ssm get-command-invocation --command-id "$COMMAND_ID" --instance-id "$INSTANCE_ID" --region "$REGION" --query 'Status' --output text 2>/dev/null || echo "Pending")
  if [[ "$S" == "Success" ]]; then
    echo ""
    aws ssm get-command-invocation --command-id "$COMMAND_ID" --instance-id "$INSTANCE_ID" --region "$REGION" --query 'StandardOutputContent' --output text 2>/dev/null || true
    echo ""
    echo "[DONE] Deploy via SSM completed."
    echo "Verify: curl -s -o /dev/null -w '%{http_code}' https://dashboard.hilovivo.com/api/health"
    exit 0
  fi
  if [[ "$S" == "Failed" || "$S" == "Cancelled" ]]; then
    echo "Command $S"
    aws ssm get-command-invocation --command-id "$COMMAND_ID" --instance-id "$INSTANCE_ID" --region "$REGION" --query 'StandardOutputContent' --output text 2>/dev/null || true
    aws ssm get-command-invocation --command-id "$COMMAND_ID" --instance-id "$INSTANCE_ID" --region "$REGION" --query 'StandardErrorContent' --output text 2>/dev/null || true
    exit 1
  fi
  sleep 1
done
echo "Timeout waiting for command."
exit 1

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
#   MAX_WAIT_ITERATIONS=900 ./scripts/deploy_production_via_ssm.sh  # longer local poll (default 600)
#
# Requires: AWS CLI, SSM agent on PROD (PingStatus Online).

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

INSTANCE_ID="${ATP_INSTANCE_ID:-i-087953603011543c5}"
REGION="${AWS_REGION:-ap-southeast-1}"
SKIP_REBUILD="${SKIP_REBUILD:-0}"
NO_CACHE="${NO_CACHE:-0}"
# Local poll limit (must exceed SSM timeout-seconds above for full rebuilds)
MAX_WAIT_ITERATIONS="${MAX_WAIT_ITERATIONS:-3900}"
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
GIT_PULL_PREFIX='export HOME=/home/ubuntu; git config --global --add safe.directory /home/ubuntu/crypto-2.0 2>/dev/null || true; git config --global --add safe.directory /home/ubuntu/crypto-2.0 2>/dev/null || true; '
# Drop broken loose ref so fetch can recreate it (avoids: cannot lock ref ... expected <old-sha>)
GIT_FETCH_CMD="${GIT_PULL_PREFIX}rm -f .git/refs/remotes/origin/main 2>/dev/null || true; git fetch origin main && git reset --hard FETCH_HEAD 2>/dev/null || git reset --hard origin/main 2>/dev/null || git pull origin main 2>/dev/null || true"
# DB must be healthy before backend-aws (see prior: postgres_hardened unhealthy blocked compose).
export GIT_FETCH_CMD
export SKIP_REBUILD
export NO_CACHE
# AWS CLI expects: --parameters 'commands=["a","b"]' (see `aws ssm send-command help` examples)
PARAMS="commands=$(python3 <<'PY'
import json, os
git = os.environ["GIT_FETCH_CMD"]
stack = (
    f'SKIP_REBUILD={os.environ.get("SKIP_REBUILD", "0")} '
    f'NO_CACHE={os.environ.get("NO_CACHE", "0")} bash scripts/aws/prod_stack_up.sh'
)
cmds = [
    "set -e",
    "cd /home/ubuntu/crypto-2.0 2>/dev/null || cd /home/ubuntu/crypto-2.0 || exit 1",
    git,
    stack,
]
print(json.dumps(cmds), end="")
PY
)"

# Docker image rebuild on PROD often exceeds 15m; 900s SSM timeout aborts mid-compose and breaks db/backend.
COMMAND_ID=$(aws ssm send-command \
  --instance-ids "$INSTANCE_ID" \
  --region "$REGION" \
  --document-name "AWS-RunShellScript" \
  --parameters "$PARAMS" \
  --timeout-seconds 3600 \
  --query 'Command.CommandId' --output text 2>&1)

if [[ -z "$COMMAND_ID" || "$COMMAND_ID" == Error* ]]; then
  echo "SSM send-command failed: $COMMAND_ID"
  exit 1
fi

echo "Command ID: $COMMAND_ID (waiting up to ~${MAX_WAIT_ITERATIONS}s local poll; SSM timeout 3600s)..."
for i in $(seq 1 "$MAX_WAIT_ITERATIONS"); do
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
echo "Timeout waiting for command (after ${MAX_WAIT_ITERATIONS}s). Check: aws ssm get-command-invocation --command-id $COMMAND_ID --instance-id $INSTANCE_ID --region $REGION"
exit 1

#!/usr/bin/env bash
# Deploy frontend-aws on PROD via AWS SSM (parity with scripts/deploy_production_via_ssm.sh).
#
# Usage:
#   ./deploy_frontend_ssm.sh
#   MAX_WAIT_ITERATIONS=900 ./deploy_frontend_ssm.sh
#
# Requires: AWS CLI, SSM Online on the instance.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$REPO_ROOT"

INSTANCE_ID="${ATP_INSTANCE_ID:-i-087953603011543c5}"
REGION="${AWS_REGION:-ap-southeast-1}"
MAX_WAIT_ITERATIONS="${MAX_WAIT_ITERATIONS:-600}"
export AWS_REGION="$REGION"

echo "=== Deploy frontend-aws via SSM (instance $INSTANCE_ID) ==="
echo ""

STATUS=$(aws ssm describe-instance-information --region "$REGION" \
  --filters "Key=InstanceIds,Values=$INSTANCE_ID" \
  --query 'InstanceInformationList[0].PingStatus' --output text 2>/dev/null || echo "NotFound")
[[ -z "$STATUS" || "$STATUS" == "None" ]] && STATUS="NotFound"

if [[ "$STATUS" != "Online" ]]; then
  echo "SSM PingStatus: $STATUS. Instance must be Online."
  echo "See: docs/runbooks/PROD_DEPLOY_WHEN_SSH_FAILS.md"
  exit 1
fi

PARAMS="commands=$(python3 <<'PY'
import json
cmds = [
    "set -e",
    "export HOME=/home/ubuntu",
    "cd /home/ubuntu/automated-trading-platform 2>/dev/null || cd /home/ubuntu/crypto-2.0 || exit 1",
    "bash scripts/aws/prod_frontend_deploy.sh",
]
print(json.dumps(cmds), end="")
PY
)"

COMMAND_ID=$(aws ssm send-command \
  --instance-ids "$INSTANCE_ID" \
  --region "$REGION" \
  --document-name "AWS-RunShellScript" \
  --parameters "$PARAMS" \
  --timeout-seconds 900 \
  --query 'Command.CommandId' --output text 2>&1)

if [[ -z "$COMMAND_ID" || "$COMMAND_ID" == Error* ]]; then
  echo "SSM send-command failed: $COMMAND_ID"
  exit 1
fi

echo "Command ID: $COMMAND_ID (waiting up to ~${MAX_WAIT_ITERATIONS}s)..."
for _ in $(seq 1 "$MAX_WAIT_ITERATIONS"); do
  S=$(aws ssm get-command-invocation --command-id "$COMMAND_ID" --instance-id "$INSTANCE_ID" --region "$REGION" --query 'Status' --output text 2>/dev/null || echo "Pending")
  if [[ "$S" == "Success" ]]; then
    echo ""
    aws ssm get-command-invocation --command-id "$COMMAND_ID" --instance-id "$INSTANCE_ID" --region "$REGION" --query 'StandardOutputContent' --output text 2>/dev/null || true
    echo ""
    echo "[DONE] Frontend deploy via SSM completed."
    echo "Verify: curl -sS -o /dev/null -w '%{http_code}\\n' --connect-timeout 8 https://dashboard.hilovivo.com/"
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
echo "Timeout after ${MAX_WAIT_ITERATIONS}s. Check: aws ssm get-command-invocation --command-id $COMMAND_ID --instance-id $INSTANCE_ID --region $REGION"
exit 1

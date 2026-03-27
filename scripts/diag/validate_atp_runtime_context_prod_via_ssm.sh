#!/usr/bin/env bash
# Run ATP runtime-context validation on PROD via SSM.
#
# Usage: ./scripts/diag/validate_atp_runtime_context_prod_via_ssm.sh
#
# Requires: AWS CLI, SSM Online on PROD (i-087953603011543c5).

set -e

INSTANCE_ID="${ATP_INSTANCE_ID:-i-087953603011543c5}"
REGION="${AWS_REGION:-ap-southeast-1}"
REPO_PATH="${REPO_PATH:-/home/ubuntu/crypto-2.0}"

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"

echo "=== ATP Runtime Context Validation (PROD $INSTANCE_ID) ==="
STATUS=$(aws ssm describe-instance-information --region "$REGION" \
  --filters "Key=InstanceIds,Values=$INSTANCE_ID" \
  --query 'InstanceInformationList[0].PingStatus' --output text 2>/dev/null || echo "NotFound")
[[ -z "$STATUS" || "$STATUS" == "None" ]] && STATUS="NotFound"
echo "SSM PingStatus: $STATUS"

if [[ "$STATUS" != "Online" ]]; then
  echo "PROD not Online for SSM. Use EC2 Instance Connect and run:"
  echo "  cd $REPO_PATH && docker compose --profile aws exec -T backend-aws python scripts/diag/validate_atp_runtime_context_prod.py"
  exit 1
fi

# Inline Python (works once fix is deployed; script file optional)
CMD_ID=$(aws ssm send-command \
  --instance-ids "$INSTANCE_ID" \
  --region "$REGION" \
  --document-name "AWS-RunShellScript" \
  --parameters 'commands=["cd /home/ubuntu/crypto-2.0 2>/dev/null || cd /home/ubuntu/crypto-2.0 || exit 1","docker compose --profile aws exec -T backend-aws python -c \"import sys; import boto3; print('BOTO3: ok'); sts=boto3.client('sts'); i=sts.get_caller_identity(); print('AWS:', i.get('Account','?')); from app.services.openclaw_client import _fetch_atp_runtime_context, build_investigation_prompt; r=_fetch_atp_runtime_context(); print('RUNTIME_LEN:', len(r)); print('RUNTIME:', (r[:900] if r else '')[:900]); u,i2=build_investigation_prompt({\"task\":{\"id\":\"v\",\"task\":\"T\",\"details\":\"d\"},\"repo_area\":{}}); print('HAS_RUNTIME:', 'Pre-fetched' in u or 'ATP PROD' in u); print('HAS_FORBID:', 'NEVER run docker' in i2); print('PROMPT:', (u[:600] if u else '')[:600])\""]' \
  --timeout-seconds 90 \
  --query 'Command.CommandId' --output text 2>&1)

if [[ -z "$CMD_ID" || "$CMD_ID" == Error* ]]; then
  echo "SSM send-command failed: $CMD_ID"
  exit 1
fi

echo "Command ID: $CMD_ID (waiting 45s...)"
for i in $(seq 1 45); do
  S=$(aws ssm get-command-invocation --command-id "$CMD_ID" --instance-id "$INSTANCE_ID" --region "$REGION" --query 'Status' --output text 2>/dev/null || echo "Pending")
  if [[ "$S" == "Success" ]]; then
    echo ""
    echo "=== Stdout ==="
    aws ssm get-command-invocation --command-id "$CMD_ID" --instance-id "$INSTANCE_ID" --region "$REGION" --query 'StandardOutputContent' --output text 2>/dev/null || true
    echo ""
    echo "=== Stderr ==="
    aws ssm get-command-invocation --command-id "$CMD_ID" --instance-id "$INSTANCE_ID" --region "$REGION" --query 'StandardErrorContent' --output text 2>/dev/null || true
    exit 0
  fi
  if [[ "$S" == "Failed" || "$S" == "Cancelled" ]]; then
    echo "Command $S"
    aws ssm get-command-invocation --command-id "$CMD_ID" --instance-id "$INSTANCE_ID" --region "$REGION" --query 'StandardOutputContent' --output text 2>/dev/null || true
    aws ssm get-command-invocation --command-id "$CMD_ID" --instance-id "$INSTANCE_ID" --region "$REGION" --query 'StandardErrorContent' --output text 2>/dev/null || true
    exit 1
  fi
  sleep 1
done
echo "Timeout."
exit 1

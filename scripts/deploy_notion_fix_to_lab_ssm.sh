#!/usr/bin/env bash
# Deploy Notion status filter fix to LAB via SSM.
# LAB: i-0d82c172235770a0d
set -e
INSTANCE_ID="${LAB_INSTANCE_ID:-i-0d82c172235770a0d}"
REGION="${AWS_REGION:-ap-southeast-1}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PARAMS_FILE="${SCRIPT_DIR}/ssm_lab_deploy_params.json"
CMD_ID=$(aws ssm send-command \
  --instance-ids "$INSTANCE_ID" \
  --region "$REGION" \
  --document-name "AWS-RunShellScript" \
  --timeout-seconds 600 \
  --parameters "file://${PARAMS_FILE}" \
  --query 'Command.CommandId' --output text)

echo "Command ID: $CMD_ID"
echo "Waiting for completion (poll every 10s, max 15 min)..."
for i in $(seq 1 90); do
  S=$(aws ssm get-command-invocation --command-id "$CMD_ID" --instance-id "$INSTANCE_ID" --region "$REGION" --query 'Status' --output text 2>/dev/null || echo "Pending")
  echo "  [$i] $S"
  if [[ "$S" == "Success" ]]; then
    echo "=== stdout ==="
    aws ssm get-command-invocation --command-id "$CMD_ID" --instance-id "$INSTANCE_ID" --region "$REGION" --query 'StandardOutputContent' --output text 2>/dev/null
    exit 0
  fi
  if [[ "$S" == "Failed" || "$S" == "Cancelled" ]]; then
    echo "FAILED. stdout:"
    aws ssm get-command-invocation --command-id "$CMD_ID" --instance-id "$INSTANCE_ID" --region "$REGION" --query 'StandardOutputContent' --output text 2>/dev/null
    echo "stderr:"
    aws ssm get-command-invocation --command-id "$CMD_ID" --instance-id "$INSTANCE_ID" --region "$REGION" --query 'StandardErrorContent' --output text 2>/dev/null
    exit 1
  fi
  sleep 10
done
echo "Timeout"
exit 1

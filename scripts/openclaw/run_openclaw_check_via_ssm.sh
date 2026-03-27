#!/usr/bin/env bash
# Run check_and_start_openclaw.sh on the Dashboard (PROD) instance via AWS SSM.
# Use this from your laptop/repo root so you don't need SSH.
#
# Usage: ./scripts/openclaw/run_openclaw_check_via_ssm.sh
# Optional: DASHBOARD_INSTANCE_ID=i-xxx AWS_REGION=ap-southeast-1 ./scripts/openclaw/run_openclaw_check_via_ssm.sh

set -e

AWS_REGION="${AWS_REGION:-ap-southeast-1}"
DASHBOARD_INSTANCE_ID="${DASHBOARD_INSTANCE_ID:-i-087953603011543c5}"

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$REPO_ROOT"

if ! command -v aws &>/dev/null; then
  echo "AWS CLI required. Install and configure aws cli."
  exit 1
fi

echo "=== OpenClaw check/start via SSM (Dashboard instance $DASHBOARD_INSTANCE_ID) ==="
STATUS=$(aws ssm describe-instance-information --region "$AWS_REGION" \
  --filters "Key=InstanceIds,Values=$DASHBOARD_INSTANCE_ID" \
  --query 'InstanceInformationList[0].PingStatus' --output text 2>/dev/null || echo "NotFound")
echo "SSM PingStatus: $STATUS"
if [[ "$STATUS" != "Online" ]]; then
  echo "Instance not Online for SSM. Use EC2 Instance Connect or fix SSM; or run the script on the server: sudo bash scripts/openclaw/check_and_start_openclaw.sh"
  exit 1
fi

COMMAND_ID=$(aws ssm send-command \
  --instance-ids "$DASHBOARD_INSTANCE_ID" \
  --region "$AWS_REGION" \
  --document-name "AWS-RunShellScript" \
  --parameters 'commands=[
    "cd /home/ubuntu/crypto-2.0 || exit 1",
    "RUN_VIA_SSM=1 sudo bash scripts/openclaw/check_and_start_openclaw.sh"
  ]' \
  --query 'Command.CommandId' \
  --output text)

if [[ -z "$COMMAND_ID" ]]; then
  echo "Failed to send command."
  exit 1
fi

echo "Command ID: $COMMAND_ID"
echo "Waiting for result (up to 90s)..."
for i in $(seq 1 90); do
  S=$(aws ssm get-command-invocation \
    --command-id "$COMMAND_ID" \
    --instance-id "$DASHBOARD_INSTANCE_ID" \
    --region "$AWS_REGION" \
    --query 'Status' --output text 2>/dev/null || echo "Pending")
  if [[ "$S" == "Success" || "$S" == "Failed" || "$S" == "Cancelled" ]]; then
    break
  fi
  sleep 1
done

echo ""
echo "=== Stdout ==="
aws ssm get-command-invocation \
  --command-id "$COMMAND_ID" \
  --instance-id "$DASHBOARD_INSTANCE_ID" \
  --region "$AWS_REGION" \
  --query 'StandardOutputContent' --output text 2>/dev/null || echo "(none)"

echo ""
echo "=== Stderr ==="
aws ssm get-command-invocation \
  --command-id "$COMMAND_ID" \
  --instance-id "$DASHBOARD_INSTANCE_ID" \
  --region "$AWS_REGION" \
  --query 'StandardErrorContent' --output text 2>/dev/null || echo "(none)"

EXIT_CODE=$(aws ssm get-command-invocation \
  --command-id "$COMMAND_ID" \
  --instance-id "$DASHBOARD_INSTANCE_ID" \
  --region "$AWS_REGION" \
  --query 'Status' --output text 2>/dev/null)
echo ""
echo "Status: $EXIT_CODE"

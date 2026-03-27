#!/usr/bin/env bash
# Run Telegram alerts diagnostic on PROD backend via AWS SSM.
# Use from repo root when PROD is reachable via SSM.
#
# Usage: ./scripts/diag/run_telegram_diagnostic_prod.sh
# Optional: INSTANCE_ID=i-xxx REGION=ap-southeast-1 ./scripts/diag/run_telegram_diagnostic_prod.sh

set -e

INSTANCE_ID="${INSTANCE_ID:-i-087953603011543c5}"
REGION="${REGION:-ap-southeast-1}"
REPO_PATH="${REPO_PATH:-/home/ubuntu/crypto-2.0}"

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$REPO_ROOT"

if ! command -v aws &>/dev/null; then
  echo "AWS CLI required. Install and configure: aws configure"
  exit 1
fi

echo "=== Telegram alerts diagnostic on PROD (instance $INSTANCE_ID) ==="
STATUS=$(aws ssm describe-instance-information --region "$REGION" \
  --filters "Key=InstanceIds,Values=$INSTANCE_ID" \
  --query 'InstanceInformationList[0].PingStatus' --output text 2>/dev/null || echo "NotFound")
echo "SSM PingStatus: $STATUS"
if [[ "$STATUS" != "Online" ]]; then
  echo "Instance not Online for SSM. Run diagnostic on the server:"
  echo "  cd $REPO_PATH && docker compose --profile aws exec backend-aws python scripts/diagnose_telegram_alerts.py"
  exit 1
fi

COMMAND_ID=$(aws ssm send-command \
  --instance-ids "$INSTANCE_ID" \
  --region "$REGION" \
  --document-name "AWS-RunShellScript" \
  --parameters 'commands=["cd '"$REPO_PATH"' || exit 1","docker compose --profile aws exec -T backend-aws python scripts/diagnose_telegram_alerts.py"]' \
  --query 'Command.CommandId' \
  --output text)

if [[ -z "$COMMAND_ID" ]]; then
  echo "Failed to send command."
  exit 1
fi

echo "Command ID: $COMMAND_ID"
echo "Waiting for result (up to 60s)..."
for i in $(seq 1 60); do
  S=$(aws ssm get-command-invocation \
    --command-id "$COMMAND_ID" \
    --instance-id "$INSTANCE_ID" \
    --region "$REGION" \
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
  --instance-id "$INSTANCE_ID" \
  --region "$REGION" \
  --query 'StandardOutputContent' --output text 2>/dev/null || echo "(none)"

echo ""
echo "=== Stderr ==="
aws ssm get-command-invocation \
  --command-id "$COMMAND_ID" \
  --instance-id "$INSTANCE_ID" \
  --region "$REGION" \
  --query 'StandardErrorContent' --output text 2>/dev/null || echo "(none)"

EXIT_CODE=$(aws ssm get-command-invocation \
  --command-id "$COMMAND_ID" \
  --instance-id "$INSTANCE_ID" \
  --region "$REGION" \
  --query 'Status' --output text 2>/dev/null)
echo ""
echo "Status: $EXIT_CODE"
[[ "$EXIT_CODE" == "Success" ]] && exit 0 || exit 1

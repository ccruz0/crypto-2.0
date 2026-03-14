#!/usr/bin/env bash
# Fix Telegram anomalies on PROD via SSM:
# 1. Set Amount USD for BTC_USD (fixes "AUTOMATIC ORDER CREATION FAILED")
# 2. Run one agent scheduler cycle (fixes "Scheduler Inactivity")
#
# Usage:
#   ./scripts/fix_telegram_anomalies_via_ssm.sh
#   BTC_AMOUNT_USD=100 ./scripts/fix_telegram_anomalies_via_ssm.sh
#
# Requires: AWS CLI, SSM agent running on PROD.

set -e
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

INSTANCE_ID="${ATP_INSTANCE_ID:-i-087953603011543c5}"
REGION="${AWS_REGION:-ap-southeast-1}"
BTC_AMOUNT_USD="${BTC_AMOUNT_USD:-50}"
export AWS_REGION="$REGION"

echo "=== Fix Telegram Anomalies via SSM (PROD $INSTANCE_ID) ==="
echo "BTC_AMOUNT_USD=\$${BTC_AMOUNT_USD}"
echo ""

STATUS=$(aws ssm describe-instance-information --region "$REGION" \
  --filters "Key=InstanceIds,Values=$INSTANCE_ID" \
  --query 'InstanceInformationList[0].PingStatus' --output text 2>/dev/null || echo "NotFound")
[[ -z "$STATUS" || "$STATUS" == "None" ]] && STATUS="NotFound"

if [[ "$STATUS" != "Online" ]]; then
  echo "SSM PingStatus: $STATUS. PROD must be Online for SSM."
  echo "Run manually on the server: ./scripts/fix_telegram_anomalies.sh"
  exit 1
fi

# Run fix on PROD: git pull, set BTC_USD amount, run scheduler cycle
# run_agent_scheduler_cycle.py is in the image; run_notion_task_pickup.sh may not exist on server
COMMAND_ID=$(aws ssm send-command \
  --instance-ids "$INSTANCE_ID" \
  --region "$REGION" \
  --document-name "AWS-RunShellScript" \
  --parameters 'commands=["set -e","cd /home/ubuntu/automated-trading-platform 2>/dev/null || cd /home/ubuntu/crypto-2.0 || exit 1","git pull origin main 2>/dev/null || true","docker compose --profile aws exec -T backend-aws python scripts/set_watchlist_trade_amount.py BTC_USD 50 2>/dev/null || true","docker compose --profile aws exec -T backend-aws python scripts/run_agent_scheduler_cycle.py 2>&1 || true"]' \
  --timeout-seconds 180 \
  --query 'Command.CommandId' --output text 2>&1)

if [[ -z "$COMMAND_ID" || "$COMMAND_ID" == Error* ]]; then
  echo "SSM send-command failed: $COMMAND_ID"
  exit 1
fi

echo "Command ID: $COMMAND_ID (waiting...)"
for i in $(seq 1 120); do
  S=$(aws ssm get-command-invocation --command-id "$COMMAND_ID" --instance-id "$INSTANCE_ID" --region "$REGION" --query 'Status' --output text 2>/dev/null || echo "Pending")
  if [[ "$S" == "Success" ]]; then
    echo ""
    aws ssm get-command-invocation --command-id "$COMMAND_ID" --instance-id "$INSTANCE_ID" --region "$REGION" --query 'StandardOutputContent' --output text 2>/dev/null || true
    echo ""
    echo "Done. Check Telegram."
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
echo "Timeout."
exit 1

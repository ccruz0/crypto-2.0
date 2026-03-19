#!/usr/bin/env bash
# Run forensic investigation for old Telegram /task message on PROD via SSM.
#
# Prerequisites: Commit and push forensic scripts to main first.
#
# Usage:
#   ./scripts/aws/run_forensic_telegram_task_via_ssm.sh
#
# This will:
#   1. Git pull on PROD (to get latest forensic scripts)
#   2. Run forensic_telegram_task_runtime.sh (host + container search, Python inspect)

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"

INSTANCE_ID="${ATP_INSTANCE_ID:-i-087953603011543c5}"
REGION="${AWS_REGION:-ap-southeast-1}"
export AWS_REGION="$REGION"

GIT_PULL='export HOME=/home/ubuntu; git config --global --add safe.directory /home/ubuntu/automated-trading-platform 2>/dev/null || true; git config --global --add safe.directory /home/ubuntu/crypto-2.0 2>/dev/null || true; '
PARAMS='commands=["set -e","cd /home/ubuntu/automated-trading-platform 2>/dev/null || cd /home/ubuntu/crypto-2.0 || exit 1","'"$GIT_PULL"'git fetch origin main && git reset --hard origin/main 2>/dev/null || git pull origin main 2>/dev/null || true","bash scripts/aws/forensic_telegram_task_runtime.sh"]'

echo "=== Forensic: Telegram /task old message (PROD via SSM) ==="
echo "Instance: $INSTANCE_ID"
echo ""

COMMAND_ID=$(aws ssm send-command \
  --instance-ids "$INSTANCE_ID" \
  --region "$REGION" \
  --document-name "AWS-RunShellScript" \
  --parameters "$PARAMS" \
  --timeout-seconds 180 \
  --query 'Command.CommandId' --output text 2>&1)

if [[ -z "$COMMAND_ID" || "$COMMAND_ID" == Error* ]]; then
  echo "SSM send-command failed: $COMMAND_ID"
  exit 1
fi

echo "Command ID: $COMMAND_ID (waiting up to ~90s)..."
for i in $(seq 1 90); do
  S=$(aws ssm get-command-invocation --command-id "$COMMAND_ID" --instance-id "$INSTANCE_ID" --region "$REGION" --query 'Status' --output text 2>/dev/null || echo "Pending")
  if [[ "$S" == "Success" ]]; then
    echo ""
    aws ssm get-command-invocation --command-id "$COMMAND_ID" --instance-id "$INSTANCE_ID" --region "$REGION" --query 'StandardOutputContent' --output text 2>/dev/null || true
    echo ""
    aws ssm get-command-invocation --command-id "$COMMAND_ID" --instance-id "$INSTANCE_ID" --region "$REGION" --query 'StandardErrorContent' --output text 2>/dev/null || true
    echo ""
    echo "[DONE] Forensic complete. Review output above for root cause."
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

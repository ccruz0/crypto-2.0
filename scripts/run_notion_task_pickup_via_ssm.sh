#!/usr/bin/env bash
# Run the Notion task pickup script on PROD via AWS SSM or EICE.
# Use when NOTION_API_KEY is already in secrets/runtime.env on the server.
#
# Usage:
#   ./scripts/run_notion_task_pickup_via_ssm.sh
#   ./scripts/run_notion_task_pickup_via_ssm.sh force   # skip SSM status check, send command anyway
#   TASK_ID=31db1837-03fe-80ca-89a5-c71bfbdbfc78 ./scripts/run_notion_task_pickup_via_ssm.sh   # specific task
#
# Requires: AWS CLI configured. If SSM is ConnectionLost, run from a machine that can SSH to PROD
# (e.g. after opening SG to your IP) or use EC2 Instance Connect in the browser.

set -e
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

INSTANCE_ID="${ATP_INSTANCE_ID:-i-087953603011543c5}"
REGION="${AWS_REGION:-ap-southeast-1}"
export AWS_REGION="$REGION"
NOTION_TASK_DB="${NOTION_TASK_DB:-eb90cfa139f94724a8b476315908510a}"
TASK_ID="${TASK_ID:-}"
FORCE="${1:-}"

# 1) Try SSM (same region as prod_status.sh)
STATUS=$(aws ssm describe-instance-information --region "$REGION" \
  --filters "Key=InstanceIds,Values=$INSTANCE_ID" \
  --query 'InstanceInformationList[0].PingStatus' --output text 2>/dev/null || echo "NotFound")
# Normalize: empty or null → NotFound
[[ -z "$STATUS" || "$STATUS" == "None" ]] && STATUS="NotFound"

if [[ "$STATUS" == "Online" || "$FORCE" == "force" ]]; then
  [[ "$FORCE" == "force" ]] && echo "=== (force: skipping SSM status check) ==="
  [[ -n "$TASK_ID" ]] && echo "=== Target task: $TASK_ID ==="
  echo "=== Notion task pickup via SSM (PROD $INSTANCE_ID) ==="
  TASK_ID_ENV=""
  [[ -n "$TASK_ID" ]] && TASK_ID_ENV="TASK_ID=$TASK_ID "
  COMMAND_ID=$(aws ssm send-command \
    --instance-ids "$INSTANCE_ID" \
    --region "$REGION" \
    --document-name "AWS-RunShellScript" \
    --parameters "commands=[\"set -e\",\"cd /home/ubuntu/crypto-2.0 2>/dev/null || cd /home/ubuntu/crypto-2.0 || exit 1\",\"git pull origin main 2>/dev/null || true\",\"${TASK_ID_ENV}NOTION_TASK_DB=eb90cfa139f94724a8b476315908510a ./scripts/run_notion_task_pickup.sh\"]" \
    --timeout-seconds 120 \
    --query 'Command.CommandId' --output text 2>&1)
  if [[ -z "$COMMAND_ID" || "$COMMAND_ID" == Error* ]]; then
    echo "SSM send-command failed: $COMMAND_ID"
    exit 1
  fi
  echo "Command ID: $COMMAND_ID (waiting up to 90s...)"
  for i in $(seq 1 90); do
    S=$(aws ssm get-command-invocation --command-id "$COMMAND_ID" --instance-id "$INSTANCE_ID" --region "$REGION" --query 'Status' --output text 2>/dev/null || echo "Pending")
    if [[ "$S" == "Success" ]]; then
      echo ""
      aws ssm get-command-invocation --command-id "$COMMAND_ID" --instance-id "$INSTANCE_ID" --region "$REGION" --query 'StandardOutputContent' --output text 2>/dev/null || true
      echo ""
      echo "Done. Check Notion and Telegram."
      exit 0
    fi
    if [[ "$S" == "Failed" || "$S" == "Cancelled" ]]; then
      DETAILS=$(aws ssm get-command-invocation --command-id "$COMMAND_ID" --instance-id "$INSTANCE_ID" --region "$REGION" --query 'StatusDetails' --output text 2>/dev/null || true)
      echo "Command $S${DETAILS:+ (StatusDetails: $DETAILS)}"
      echo "--- stdout ---"
      aws ssm get-command-invocation --command-id "$COMMAND_ID" --instance-id "$INSTANCE_ID" --region "$REGION" --query 'StandardOutputContent' --output text 2>/dev/null || true
      echo "--- stderr ---"
      aws ssm get-command-invocation --command-id "$COMMAND_ID" --instance-id "$INSTANCE_ID" --region "$REGION" --query 'StandardErrorContent' --output text 2>/dev/null || true
      echo "If StatusDetails is Undeliverable, the command never ran on the instance; run the pickup on the server manually (see below)."
      exit 1
    fi
    sleep 1
  done
  echo "Timeout waiting for command."
  exit 1
fi

# 2) SSM not available
echo "SSM PingStatus: $STATUS (not Online). Use same region as prod_status: AWS_REGION=$REGION"
echo "If ./scripts/aws/prod_status.sh shows PROD Online, try: $0 force"
echo ""
echo "Run the pickup on the server manually:"
echo "  1. Connect to PROD (EC2 Instance Connect in browser or SSH after opening SG to your IP)."
echo "  2. cd /home/ubuntu/crypto-2.0"
echo "  3. git pull origin main"
echo "  4. NOTION_TASK_DB=$NOTION_TASK_DB ./scripts/run_notion_task_pickup.sh"
echo "  5. For a specific task: TASK_ID=<notion-page-id> NOTION_TASK_DB=$NOTION_TASK_DB ./scripts/run_notion_task_pickup.sh"
echo ""
echo "See: docs/aws/COMANDOS_PARA_EJECUTAR.md §6, docs/runbooks/NOTION_TASK_TO_CURSOR_AND_DEPLOY.md"
exit 1

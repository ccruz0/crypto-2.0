#!/usr/bin/env bash
# Deploy Notion runtime env fix to LAB, verify vars, run one pickup, and collect logs.
# Usage: ./scripts/aws/deploy_notion_runtime_to_lab_and_verify.sh
# Requires: AWS CLI configured; LAB instance Online in SSM.
set -euo pipefail

LAB_INSTANCE_ID="${LAB_INSTANCE_ID:-i-0d82c172235770a0d}"
REGION="${AWS_REGION:-ap-southeast-1}"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"

get_output() {
  local cmd_id="$1"
  aws ssm get-command-invocation --command-id "$cmd_id" --instance-id "$LAB_INSTANCE_ID" --region "$REGION" --query 'StandardOutputContent' --output text 2>/dev/null || echo ""
}

get_status() {
  local cmd_id="$1"
  aws ssm get-command-invocation --command-id "$cmd_id" --instance-id "$LAB_INSTANCE_ID" --region "$REGION" --query 'Status' --output text 2>/dev/null || echo "Pending"
}

wait_cmd() {
  local cmd_id="$1" max="${2:-90}"
  for i in $(seq 1 "$max"); do
    S=$(get_status "$cmd_id")
    if [[ "$S" == "Success" ]]; then return 0; fi
    if [[ "$S" == "Failed" || "$S" == "Cancelled" ]]; then return 1; fi
    sleep 5
  done
  return 1
}

# --- Step 1: Deploy (update code, render env, restart backend-aws) ---
echo "=== Step 1: Deploy to LAB (git pull, render_runtime_env, restart backend-aws) ==="
CMD1=$(aws ssm send-command \
  --instance-ids "$LAB_INSTANCE_ID" \
  --region "$REGION" \
  --document-name "AWS-RunShellScript" \
  --timeout-seconds 600 \
  --parameters 'commands=[
    "set -e",
    "sudo chown -R ubuntu:ubuntu /home/ubuntu/automated-trading-platform 2>/dev/null || true",
    "sudo -u ubuntu bash -c \"export HOME=/home/ubuntu; cd /home/ubuntu/automated-trading-platform && git config --global --add safe.directory /home/ubuntu/automated-trading-platform && git pull origin main && bash scripts/aws/render_runtime_env.sh && docker compose --profile aws up -d backend-aws\"",
    "echo === Step 1 done ==="
  ]' \
  --query 'Command.CommandId' --output text)
echo "Command ID: $CMD1 (waiting up to 3 min)..."
if ! wait_cmd "$CMD1" 36; then
  echo "Step 1 FAILED. stdout:"; get_output "$CMD1"
  aws ssm get-command-invocation --command-id "$CMD1" --instance-id "$LAB_INSTANCE_ID" --region "$REGION" --query 'StandardErrorContent' --output text 2>/dev/null || true
  exit 1
fi
echo "Step 1 output:"; get_output "$CMD1"
echo ""

# --- Step 2: Verify Notion vars in container ---
echo "=== Step 2: Verify NOTION_API_KEY and NOTION_TASK_DB in backend-aws ==="
CMD2=$(aws ssm send-command \
  --instance-ids "$LAB_INSTANCE_ID" \
  --region "$REGION" \
  --document-name "AWS-RunShellScript" \
  --timeout-seconds 60 \
  --parameters 'commands=[
    "cd /home/ubuntu/automated-trading-platform",
    "docker compose --profile aws exec -T backend-aws sh -c '\''if [ -n \"$NOTION_API_KEY\" ]; then echo NOTION_API_KEY=present; else echo NOTION_API_KEY=not present; fi'\''",
    "docker compose --profile aws exec -T backend-aws sh -c '\''if [ -n \"$NOTION_TASK_DB\" ]; then echo NOTION_TASK_DB=present; else echo NOTION_TASK_DB=not present; fi'\''",
    "docker compose --profile aws exec -T backend-aws printenv NOTION_TASK_DB"
  ]' \
  --query 'Command.CommandId' --output text)
echo "Command ID: $CMD2 (waiting...)"
wait_cmd "$CMD2" 24 || true
VERIFY_OUT=$(get_output "$CMD2")
echo "$VERIFY_OUT"
echo ""

# --- Step 3: Run one pickup cycle ---
echo "=== Step 3: Run run_notion_task_pickup.sh ==="
CMD3=$(aws ssm send-command \
  --instance-ids "$LAB_INSTANCE_ID" \
  --region "$REGION" \
  --document-name "AWS-RunShellScript" \
  --timeout-seconds 300 \
  --parameters 'commands=[
    "set -e",
    "cd /home/ubuntu/automated-trading-platform",
    "./scripts/run_notion_task_pickup.sh"
  ]' \
  --query 'Command.CommandId' --output text)
echo "Command ID: $CMD3 (waiting up to 5 min)..."
wait_cmd "$CMD3" 60 || true
PICKUP_OUT=$(get_output "$CMD3")
echo "$PICKUP_OUT"
ST3=$(get_status "$CMD3")
if [[ "$ST3" != "Success" ]]; then
  echo "Step 3 stderr:"; aws ssm get-command-invocation --command-id "$CMD3" --instance-id "$LAB_INSTANCE_ID" --region "$REGION" --query 'StandardErrorContent' --output text 2>/dev/null || true
fi
echo ""

# --- Step 4: Backend logs ---
echo "=== Step 4: backend-aws logs (tail 300) ==="
CMD4=$(aws ssm send-command \
  --instance-ids "$LAB_INSTANCE_ID" \
  --region "$REGION" \
  --document-name "AWS-RunShellScript" \
  --timeout-seconds 60 \
  --parameters 'commands=[
    "cd /home/ubuntu/automated-trading-platform",
    "docker compose --profile aws logs --tail=300 backend-aws"
  ]' \
  --query 'Command.CommandId' --output text)
echo "Command ID: $CMD4 (waiting...)"
wait_cmd "$CMD4" 24 || true
LOGS_OUT=$(get_output "$CMD4")
echo "$LOGS_OUT"
echo ""

# --- Summary for user ---
echo "========== SUMMARY (send these to operator) =========="
echo "--- Presence checks ---"
echo "$VERIFY_OUT"
echo "--- run_notion_task_pickup.sh output ---"
echo "$PICKUP_OUT"
echo "--- backend-aws logs (last 300 lines) ---"
echo "$LOGS_OUT"

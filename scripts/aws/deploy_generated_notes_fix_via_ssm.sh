#!/usr/bin/env bash
# Deploy generated-notes permission fix via SSM: pull, rebuild backend-aws, verify.
# Run from repo root. Requires: code pushed to main, AWS CLI configured.
#
# Usage: ./scripts/aws/deploy_generated_notes_fix_via_ssm.sh
set -euo pipefail

INSTANCE_ID="${ATP_EC2_INSTANCE_ID:-i-087953603011543c5}"
REGION="${ATP_AWS_REGION:-ap-southeast-1}"

PING=$(aws ssm describe-instance-information --region "$REGION" --filters "Key=InstanceIds,Values=$INSTANCE_ID" --query 'InstanceInformationList[0].PingStatus' --output text 2>/dev/null || echo "None")
if [ "$PING" != "Online" ]; then
    echo "Instance $INSTANCE_ID SSM PingStatus=$PING (need Online)."
    exit 1
fi

echo "Deploying generated-notes fix via SSM (instance=$INSTANCE_ID)"
echo ""

# 1) Pull, build backend-aws, restart
echo "1) Pulling code, rebuilding backend-aws, restarting..."
CMD_ID=$(aws ssm send-command \
    --instance-ids "$INSTANCE_ID" \
    --region "$REGION" \
    --document-name "AWS-RunShellScript" \
    --timeout-seconds 600 \
    --parameters 'commands=[
        "set -e",
        "cd /home/ubuntu/crypto-2.0 || cd ~/automated-trading-platform || { echo ERR: repo not found; exit 1; }",
        "git config --global --add safe.directory /home/ubuntu/crypto-2.0 2>/dev/null || true",
        "echo Pulling latest code...",
        "git pull origin main || true",
        "echo Rendering secrets...",
        "bash scripts/aws/render_runtime_env.sh 2>/dev/null || true",
        "echo Rebuilding backend-aws...",
        "docker compose --profile aws build backend-aws --no-cache",
        "echo Restarting backend-aws with new image...",
        "docker compose --profile aws stop backend-aws || true",
        "docker compose --profile aws rm -f backend-aws 2>/dev/null || true",
        "docker compose --profile aws up -d backend-aws",
        "echo Waiting 45s for startup...",
        "sleep 45",
        "echo Verifying backend health...",
        "curl -sf --connect-timeout 5 http://127.0.0.1:8002/ping_fast && echo OK || echo FAIL"
    ]' \
    --query 'Command.CommandId' \
    --output text)

if [ -z "$CMD_ID" ]; then
    echo "Failed to send SSM command"
    exit 1
fi

echo "Command ID: $CMD_ID — waiting (build can take 8–12 min)..."
for i in $(seq 1 90); do
  STATUS=$(aws ssm get-command-invocation --command-id "$CMD_ID" --instance-id "$INSTANCE_ID" --region "$REGION" --query "Status" --output text 2>/dev/null || echo "InProgress")
  [ "$STATUS" = "Success" ] && echo "Done." && break
  [ "$STATUS" = "Failed" ] && echo "Deploy failed." && break
  [ $((i % 6)) -eq 0 ] && echo "  ... $((i*10))s"
  sleep 10
done

echo ""
echo "=== Deploy output ==="
aws ssm get-command-invocation \
    --command-id "$CMD_ID" \
    --instance-id "$INSTANCE_ID" \
    --region "$REGION" \
    --query '[Status, StandardOutputContent, StandardErrorContent]' --output text | tr '\t' '\n'
echo ""

# 2) Verify generated-notes directory
echo "2) Verifying docs/agents/generated-notes..."
VERIFY_ID=$(aws ssm send-command \
    --instance-ids "$INSTANCE_ID" \
    --region "$REGION" \
    --document-name "AWS-RunShellScript" \
    --parameters 'commands=[
        "CONTAINER=$(docker ps --format \"{{.Names}}\" | grep -E \"backend.*aws\" | grep -v canary | head -1)",
        "echo Backend container: $CONTAINER",
        "docker exec $CONTAINER ls -la /app/docs/agents/generated-notes 2>/dev/null || echo Directory missing or not writable",
        "docker exec $CONTAINER id 2>/dev/null || true"
    ]' \
    --query 'Command.CommandId' \
    --output text)

aws ssm wait command-executed --command-id "$VERIFY_ID" --instance-id "$INSTANCE_ID" --region "$REGION" || true

echo ""
echo "=== Verification output ==="
aws ssm get-command-invocation \
    --command-id "$VERIFY_ID" \
    --instance-id "$INSTANCE_ID" \
    --region "$REGION" \
    --query '[Status, StandardOutputContent, StandardErrorContent]' --output text | tr '\t' '\n'

echo ""
echo "Done. Trigger a documentation task to confirm writes succeed."

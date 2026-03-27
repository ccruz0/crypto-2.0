#!/bin/bash
# Deploy Telegram reliability fix: migration + full backend rebuild.
# Ensures telegram_update_dedup table exists and updated code is running.
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

INSTANCE_ID="${ATP_INSTANCE_ID:-i-087953603011543c5}"
REGION="${AWS_REGION:-ap-southeast-1}"

echo "🚀 Deploying Telegram reliability fix via SSM"
echo "============================================="

if ! command -v aws &> /dev/null; then
    echo "❌ AWS CLI not found."
    exit 1
fi

echo "📤 Sending deploy command (git pull + migration + backend rebuild)..."

COMMAND_ID=$(aws ssm send-command \
    --instance-ids $INSTANCE_ID \
    --document-name "AWS-RunShellScript" \
    --parameters 'commands=["set -e","REPO=/home/ubuntu/crypto-2.0","[ -d $REPO ] || REPO=/home/ubuntu/crypto-2.0","cd $REPO || exit 1","sudo chown -R ubuntu:ubuntu $REPO || true","sudo -u ubuntu bash -c \"cd $REPO; git fetch origin && git reset --hard origin/main\" || true","mkdir -p docs/agents/bug-investigations && sudo chown -R 10001:10001 docs/agents/bug-investigations || true","bash scripts/aws/render_runtime_env.sh 2>/dev/null || true","docker compose --profile aws up -d db","sleep 15","cd $REPO && docker compose --profile aws exec -T db sh -c \"PGPASSWORD=\\$POSTGRES_PASSWORD psql -U trader -d atp\" < backend/migrations/add_telegram_update_dedup.sql || true","docker compose --profile aws build --no-cache backend-aws","docker compose --profile aws up -d","sleep 25","curl -sf --connect-timeout 5 http://127.0.0.1:8002/ping_fast && echo Backend OK || echo Backend not ready","sudo systemctl restart nginx 2>/dev/null || true","docker compose --profile aws ps"]' \
    --region $REGION \
    --timeout-seconds 600 \
    --output text \
    --query 'Command.CommandId' 2>&1)

if [[ $COMMAND_ID == Error* ]] || [ -z "$COMMAND_ID" ]; then
    echo "❌ Failed: $COMMAND_ID"
    exit 1
fi

echo "✅ Command ID: $COMMAND_ID"
echo "⏳ Waiting 300s for command to finish..."
sleep 300

echo ""
echo "📊 Result:"
aws ssm get-command-invocation \
    --command-id $COMMAND_ID \
    --instance-id $INSTANCE_ID \
    --region $REGION \
    --query '[Status, StandardOutputContent, StandardErrorContent]' \
    --output text 2>&1 | head -100

echo ""
echo "🎉 Deploy finished. Validate in ATP Control: /start, /help, /runtime-check, /investigate, /agent"

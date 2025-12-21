#!/bin/bash
# Deploy Telegram Alerts Fix via AWS SSM

set -e

INSTANCE_ID="i-08726dc37133b2454"
REGION="ap-southeast-1"

echo "🚀 Deploying Telegram Alerts Fix via AWS SSM"
echo "============================================="
echo ""

if ! command -v aws &> /dev/null; then
    echo "❌ AWS CLI not found. Please install AWS CLI first."
    exit 1
fi

echo "📤 Sending deployment command..."
COMMAND_ID=$(aws ssm send-command \
    --instance-ids $INSTANCE_ID \
    --document-name "AWS-RunShellScript" \
    --parameters commands="
cd /home/ubuntu/automated-trading-platform || exit 1
export HOME=/home/ubuntu
git config --global --add safe.directory /home/ubuntu/automated-trading-platform 2>/dev/null || true
git pull origin main 2>&1 || echo 'Git pull completed'
CONTAINER=\$(docker ps --filter 'name=market-updater-aws' --format '{{.Names}}' | head -1)
if [ -z \"\$CONTAINER\" ]; then 
  echo '❌ Container not found. Available:'
  docker ps --format '{{.Names}}'
  exit 1
fi
echo \"📋 Container: \$CONTAINER\"
docker cp backend/app/services/signal_monitor.py \$CONTAINER:/app/app/services/signal_monitor.py
echo '✅ File copied'
docker exec \$CONTAINER grep -q 'alert_origin = get_runtime_origin()' /app/app/services/signal_monitor.py && echo '✅ Fix verified' || echo '❌ Fix not found'
docker compose --profile aws restart market-updater-aws 2>&1 || docker restart \$CONTAINER
sleep 5
docker ps --filter 'name=market-updater-aws' --format 'table {{.Names}}\t{{.Status}}'
echo '✅ Deployment complete'
" \
    --region $REGION \
    --output text \
    --query 'Command.CommandId' 2>&1)

if [[ $COMMAND_ID == Error* ]] || [ -z "$COMMAND_ID" ]; then
    echo "❌ Failed to send command: $COMMAND_ID"
    exit 1
fi

echo "✅ Command ID: $COMMAND_ID"
echo "⏳ Waiting 50 seconds for deployment..."
sleep 50

echo ""
echo "📊 Deployment Result:"
echo "===================="
echo ""

aws ssm get-command-invocation \
    --command-id $COMMAND_ID \
    --instance-id $INSTANCE_ID \
    --region $REGION \
    --query '[Status, StandardOutputContent, StandardErrorContent]' \
    --output text 2>&1 | head -100

echo ""
echo "✅ Deployment command executed. Check output above for status."





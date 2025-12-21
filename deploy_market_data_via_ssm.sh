#!/bin/bash
set -e

INSTANCE_ID="i-08726dc37133b2454"
REGION="ap-southeast-1"

echo "🚀 Deploying Market Data Fixes via AWS Session Manager (SSM)"
echo "============================================================="
echo ""

if ! command -v aws &> /dev/null; then
    echo "❌ AWS CLI not found. Please install AWS CLI."
    exit 1
fi

echo "📤 Step 1: Pulling latest code..."
COMMAND_ID=$(aws ssm send-command \
    --instance-ids $INSTANCE_ID \
    --document-name "AWS-RunShellScript" \
    --parameters 'commands=["cd /home/ubuntu/automated-trading-platform","git pull origin main || git pull"]' \
    --region $REGION \
    --output text \
    --query 'Command.CommandId' 2>&1)

if [[ $COMMAND_ID == Error* ]] || [ -z "$COMMAND_ID" ]; then
    echo "❌ Failed to send command: $COMMAND_ID"
    exit 1
fi

echo "✅ Command ID: $COMMAND_ID"
echo "⏳ Waiting 15 seconds for git pull..."
sleep 15

echo ""
echo "📊 Git Pull Result:"
aws ssm get-command-invocation \
    --command-id $COMMAND_ID \
    --instance-id $INSTANCE_ID \
    --region $REGION \
    --query '[Status, StandardOutputContent]' \
    --output text 2>&1 | head -20

echo ""
echo "🔄 Step 2: Restarting backend service..."
COMMAND_ID2=$(aws ssm send-command \
    --instance-ids $INSTANCE_ID \
    --document-name "AWS-RunShellScript" \
    --parameters 'commands=["cd /home/ubuntu/automated-trading-platform","docker-compose --profile aws restart backend-aws"]' \
    --region $REGION \
    --output text \
    --query 'Command.CommandId' 2>&1)

echo "✅ Restart command ID: $COMMAND_ID2"
echo "⏳ Waiting 10 seconds for restart..."
sleep 10

echo ""
echo "📊 Restart Result:"
aws ssm get-command-invocation \
    --command-id $COMMAND_ID2 \
    --instance-id $INSTANCE_ID \
    --region $REGION \
    --query '[Status, StandardOutputContent]' \
    --output text 2>&1 | head -10

echo ""
echo "📋 Step 3: Checking market-updater-aws logs (last 50 lines)..."
echo "============================================================="
COMMAND_ID3=$(aws ssm send-command \
    --instance-ids $INSTANCE_ID \
    --document-name "AWS-RunShellScript" \
    --parameters 'commands=["cd /home/ubuntu/automated-trading-platform","docker-compose --profile aws logs market-updater-aws --tail=50"]' \
    --region $REGION \
    --output text \
    --query 'Command.CommandId' 2>&1)

echo "✅ Logs command ID: $COMMAND_ID3"
echo "⏳ Waiting 5 seconds..."
sleep 5

echo ""
aws ssm get-command-invocation \
    --command-id $COMMAND_ID3 \
    --instance-id $INSTANCE_ID \
    --region $REGION \
    --query 'StandardOutputContent' \
    --output text 2>&1 | head -60

echo ""
echo "✅ Deployment complete!"
echo ""
echo "Look for these patterns in logs:"
echo "  ✅ '✅ Fetched {N} candles from Binance' - Success"
echo "  ✅ '✅ Indicators for {symbol}: RSI=...' - Real calculations"
echo "  ⚠️  '⚠️ Only {N} candles' - Insufficient data"
echo "  ⚠️  '⚠️ No OHLCV data' - Fetch failures"


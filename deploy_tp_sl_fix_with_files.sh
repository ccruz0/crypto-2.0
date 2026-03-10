#!/bin/bash
set -e

INSTANCE_ID="i-087953603011543c5"
REGION="ap-southeast-1"

echo "🚀 Deploying TP/SL Value fix with file copy to AWS"
echo "==========================================="
echo ""

if ! command -v aws &> /dev/null; then
    echo "❌ AWS CLI not found."
    exit 1
fi

echo "📤 Copying updated page.tsx to server..."

# Create a base64 encoded version of the file
FILE_CONTENT=$(cat frontend/src/app/page.tsx | base64)

echo "📤 Sending deployment command with file update..."

COMMAND_ID=$(aws ssm send-command \
    --instance-ids $INSTANCE_ID \
    --document-name "AWS-RunShellScript" \
    --parameters "commands=[
        \"cd /home/ubuntu/automated-trading-platform/frontend/src/app\",
        \"echo '$FILE_CONTENT' | base64 -d > page.tsx.new\",
        \"mv page.tsx.new page.tsx\",
        \"grep -n 'TP Value' page.tsx | head -2\",
        \"cd /home/ubuntu/automated-trading-platform\",
        \"echo 'Building frontend Docker image...'\",
        \"docker compose --profile aws build --no-cache frontend-aws\",
        \"docker compose --profile aws stop frontend-aws\",
        \"docker compose --profile aws rm -f frontend-aws\",
        \"docker compose --profile aws up -d frontend-aws\",
        \"sleep 15\",
        \"docker compose --profile aws ps frontend-aws\"
    ]" \
    --region $REGION \
    --output text \
    --query 'Command.CommandId' 2>&1)

if [[ $COMMAND_ID == Error* ]] || [ -z "$COMMAND_ID" ]; then
    echo "❌ Failed: $COMMAND_ID"
    exit 1
fi

echo "✅ Command ID: $COMMAND_ID"
echo "⏳ Waiting 90 seconds for execution..."
sleep 90

echo ""
echo "📊 Result:"
aws ssm get-command-invocation \
    --command-id $COMMAND_ID \
    --instance-id $INSTANCE_ID \
    --region $REGION \
    --query '[Status, StandardOutputContent]' \
    --output text 2>&1 | head -50

echo ""
echo "🎉 Deployment initiated!"

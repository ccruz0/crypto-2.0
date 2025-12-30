#!/bin/bash
set -e

INSTANCE_ID="i-08726dc37133b2454"
REGION="ap-southeast-1"

echo "🚀 Deploying OrdersTab.tsx fix via AWS Session Manager (SSM)"
echo "==========================================="
echo ""

if ! command -v aws &> /dev/null; then
    echo "❌ AWS CLI not found."
    exit 1
fi

# Read the file content and base64 encode it
FILE_CONTENT=$(cat frontend/src/app/components/tabs/OrdersTab.tsx | base64 -i -)

echo "📤 Sending OrdersTab.tsx file to AWS..."

# Send command via SSM - write to host filesystem first, then rebuild
COMMAND_ID=$(aws ssm send-command \
    --instance-ids $INSTANCE_ID \
    --document-name "AWS-RunShellScript" \
    --parameters "commands=[
      'cd /home/ubuntu/automated-trading-platform',
      'echo \"$FILE_CONTENT\" | base64 -d > frontend/src/app/components/tabs/OrdersTab.tsx',
      'echo \"✅ File written to host filesystem\"',
      'docker-compose --profile aws build frontend-aws',
      'echo \"✅ Frontend image rebuilt\"',
      'docker-compose --profile aws up -d frontend-aws',
      'echo \"✅ Frontend restarted\"',
      'sleep 10',
      'docker-compose --profile aws ps frontend-aws'
    ]" \
    --region $REGION \
    --output text \
    --query 'Command.CommandId' 2>&1)

if [[ $COMMAND_ID == Error* ]] || [ -z "$COMMAND_ID" ]; then
    echo "❌ Failed: $COMMAND_ID"
    exit 1
fi

echo "✅ Command ID: $COMMAND_ID"
echo "⏳ Waiting 90 seconds for rebuild and restart..."
sleep 90

echo ""
echo "📊 Result:"
aws ssm get-command-invocation \
    --command-id $COMMAND_ID \
    --instance-id $INSTANCE_ID \
    --region $REGION \
    --query '[Status, StandardOutputContent, StandardErrorContent]' \
    --output text 2>&1

echo ""
echo "🎉 OrdersTab.tsx deployment completed!"



#!/bin/bash
set -e

INSTANCE_ID="i-08726dc37133b2454"
REGION="ap-southeast-1"

echo "🚀 Deploying TP/SL Value fix via Git pull"
echo "==========================================="
echo ""

if ! command -v aws &> /dev/null; then
    echo "❌ AWS CLI not found."
    exit 1
fi

echo "📤 Sending deployment command to pull latest code and rebuild..."

COMMAND_ID=$(aws ssm send-command \
    --instance-ids $INSTANCE_ID \
    --document-name "AWS-RunShellScript" \
    --parameters 'commands=[
        "cd /home/ubuntu/automated-trading-platform",
        "git fetch origin",
        "git reset --hard origin/main",
        "echo \"Verifying TP Value in code...\"",
        "grep -n \"TP Value\" frontend/src/app/page.tsx | head -2",
        "echo \"Building frontend Docker image...\"",
        "docker compose --profile aws build --no-cache frontend-aws",
        "docker compose --profile aws stop frontend-aws",
        "docker compose --profile aws rm -f frontend-aws",
        "docker compose --profile aws up -d frontend-aws",
        "sleep 15",
        "docker compose --profile aws ps frontend-aws"
    ]' \
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
    --output text 2>&1 | head -100

echo ""
echo "🎉 Deployment initiated!"

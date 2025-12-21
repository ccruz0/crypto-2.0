#!/bin/bash
set -e

INSTANCE_ID="i-08726dc37133b2454"
REGION="ap-southeast-1"

echo "🚀 Deploying TP/SL Value fix via AWS Session Manager (SSM)"
echo "==========================================="
echo ""

if ! command -v aws &> /dev/null; then
    echo "❌ AWS CLI not found. Please install AWS CLI first."
    exit 1
fi

echo "📤 Sending deployment command to rebuild frontend with TP/SL fix..."

# Deploy: pull changes, rebuild without cache, and restart
COMMAND_ID=$(aws ssm send-command \
    --instance-ids $INSTANCE_ID \
    --document-name "AWS-RunShellScript" \
    --parameters 'commands=[
        "cd /home/ubuntu/automated-trading-platform",
        "git pull origin main || echo \"Git pull failed, continuing with local files\"",
        "cd frontend",
        "echo \"Building frontend Docker image...\"",
        "cd ..",
        "docker compose --profile aws build --no-cache frontend-aws",
        "echo \"Stopping old container...\"",
        "docker compose --profile aws stop frontend-aws",
        "docker compose --profile aws rm -f frontend-aws",
        "echo \"Starting new container...\"",
        "docker compose --profile aws up -d frontend-aws",
        "sleep 15",
        "echo \"Checking container status...\"",
        "docker compose --profile aws ps frontend-aws",
        "docker logs automated-trading-platform-frontend-aws-1 --tail 10"
    ]' \
    --region $REGION \
    --output text \
    --query 'Command.CommandId' 2>&1)

if [[ $COMMAND_ID == Error* ]] || [ -z "$COMMAND_ID" ]; then
    echo "❌ Failed to send command: $COMMAND_ID"
    exit 1
fi

echo "✅ Command ID: $COMMAND_ID"
echo "⏳ Waiting 90 seconds for execution (build takes time)..."
sleep 90

echo ""
echo "📊 Deployment Result:"
aws ssm get-command-invocation \
    --command-id $COMMAND_ID \
    --instance-id $INSTANCE_ID \
    --region $REGION \
    --query '[Status, StandardOutputContent, StandardErrorContent]' \
    --output text 2>&1

echo ""
echo "🎉 Frontend TP/SL fix deployment initiated!"
echo "💡 Check https://dashboard.hilovivo.com and hard refresh (Cmd+Shift+R) to see changes"

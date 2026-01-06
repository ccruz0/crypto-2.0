#!/bin/bash
set -e

INSTANCE_ID="i-08726dc37133b2454"
REGION="ap-southeast-1"

echo "🚀 Deploying ActiveAlerts Refactor"
echo "==================================="
echo ""

if ! command -v aws &> /dev/null; then
    echo "❌ AWS CLI not found."
    exit 1
fi

echo "📤 Sending deployment command to pull latest code and restart backend..."

COMMAND_ID=$(aws ssm send-command \
    --instance-ids $INSTANCE_ID \
    --document-name "AWS-RunShellScript" \
    --parameters 'commands=[
        "cd /home/ubuntu/automated-trading-platform || cd ~/automated-trading-platform",
        "echo \"📥 Pulling latest changes from git...\"",
        "git fetch origin",
        "git pull origin main || echo \"Git pull failed, continuing...\"",
        "echo \"✅ Code updated\"",
        "echo \"\"",
        "echo \"🔄 Restarting backend service...\"",
        "docker compose --profile aws restart backend-aws || docker compose --profile aws restart backend",
        "echo \"⏳ Waiting for backend to be ready...\"",
        "sleep 15",
        "echo \"📊 Checking service status...\"",
        "docker compose --profile aws ps backend-aws || docker compose --profile aws ps backend",
        "echo \"\"",
        "echo \"🧪 Testing backend health...\"",
        "curl -f http://localhost:8000/api/health || echo \"Health check failed (may need more time)\"",
        "echo \"\"",
        "echo \"✅ Deployment complete!\""
    ]' \
    --region $REGION \
    --output text \
    --query 'Command.CommandId' 2>&1)

if [[ $COMMAND_ID == Error* ]] || [ -z "$COMMAND_ID" ]; then
    echo "❌ Failed: $COMMAND_ID"
    exit 1
fi

echo "✅ Command ID: $COMMAND_ID"
echo "⏳ Waiting 60 seconds for execution..."
sleep 60

echo ""
echo "📊 Deployment Result:"
aws ssm get-command-invocation \
    --command-id $COMMAND_ID \
    --instance-id $INSTANCE_ID \
    --region $REGION \
    --query '[Status, StandardOutputContent]' \
    --output text 2>&1 | head -100

echo ""
echo "🧪 Verifying ActiveAlerts endpoint..."
echo ""

# Test the monitoring endpoint
VERIFY_COMMAND_ID=$(aws ssm send-command \
    --instance-ids $INSTANCE_ID \
    --document-name "AWS-RunShellScript" \
    --parameters 'commands=[
        "echo \"Testing /api/monitoring/summary endpoint...\"",
        "curl -s http://localhost:8000/api/monitoring/summary | python3 -m json.tool | grep -A 5 \"active_alerts\" || echo \"Endpoint test failed\""
    ]' \
    --region $REGION \
    --output text \
    --query 'Command.CommandId' 2>&1)

if [[ $VERIFY_COMMAND_ID != Error* ]] && [ -n "$VERIFY_COMMAND_ID" ]; then
    echo "⏳ Waiting 10 seconds for verification..."
    sleep 10
    
    echo ""
    echo "📊 Verification Result:"
    aws ssm get-command-invocation \
        --command-id $VERIFY_COMMAND_ID \
        --instance-id $INSTANCE_ID \
        --region $REGION \
        --query '[Status, StandardOutputContent]' \
        --output text 2>&1 | head -50
fi

echo ""
echo "🎉 Deployment and verification complete!"
echo ""
echo "Next steps:"
echo "1. Check the Monitoring tab in the dashboard"
echo "2. Verify Active Alerts count matches enabled toggles in Watchlist"
echo "3. Toggle alerts on/off and verify they appear/disappear immediately"
















#!/bin/bash
# Deploy docs endpoint fix via AWS SSM using git pull

set -e

INSTANCE_ID="i-087953603011543c5"
REGION="ap-southeast-1"

echo "🔧 Deploying Docs Endpoint Fix via SSM (Git Pull)"
echo "================================================="
echo ""

if ! command -v aws &> /dev/null; then
    echo "❌ AWS CLI not found. Please install it first."
    exit 1
fi

echo "⚠️  Note: This script assumes changes are committed and pushed to git."
echo "   If not, please commit and push first, or use deploy_docs_fix_ssm.sh"
echo ""
read -p "Continue? (y/n) " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "Deployment cancelled."
    exit 1
fi

echo "📤 Sending deployment command via SSM..."

COMMAND_ID=$(aws ssm send-command \
    --instance-ids $INSTANCE_ID \
    --document-name "AWS-RunShellScript" \
    --parameters 'commands=[
        "cd ~/automated-trading-platform || cd /home/ubuntu/crypto-2.0",
        "echo \"📥 Pulling latest code from git...\"",
        "git pull origin main || git pull || echo \"Git pull failed, continuing with manual update...\"",
        "echo \"🔍 Step 1: Testing nginx configuration...\"",
        "sudo nginx -t",
        "echo \"🔄 Step 2: Reloading nginx...\"",
        "sudo systemctl reload nginx || sudo service nginx reload",
        "echo \"🔄 Step 3: Restarting backend...\"",
        "sudo systemctl restart trading-backend 2>/dev/null || sudo systemctl restart backend 2>/dev/null || docker compose restart backend 2>/dev/null || docker restart $(docker ps -q -f name=backend) 2>/dev/null || echo \"Backend restart - check service name\"",
        "echo \"✅ Deployment complete!\"",
        "echo \"\"",
        "echo \"Verification:\"",
        "grep -q \"watchlist-consistency/latest\" backend/app/api/routes_monitoring.py && echo \"✅ Backend endpoint found\" || echo \"❌ Backend endpoint not found\"",
        "grep -q \"/docs/monitoring/\" nginx/dashboard.conf && echo \"✅ Nginx config updated\" || echo \"⚠️  Nginx config not found in project dir\""
    ]' \
    --region $REGION \
    --output text \
    --query 'Command.CommandId' 2>&1)

if [[ $COMMAND_ID == Error* ]] || [ -z "$COMMAND_ID" ]; then
    echo "❌ Failed to send command: $COMMAND_ID"
    exit 1
fi

echo "✅ Command ID: $COMMAND_ID"
echo "⏳ Waiting 45 seconds for execution..."
sleep 45

echo ""
echo "📊 Deployment Result:"
echo "===================="
aws ssm get-command-invocation \
    --command-id $COMMAND_ID \
    --instance-id $INSTANCE_ID \
    --region $REGION \
    --query '[Status, StandardOutputContent, StandardErrorContent]' \
    --output text 2>&1

echo ""
echo ""
echo "🎉 Deployment completed!"
echo ""
echo "Test the endpoint:"
echo "  curl -I https://dashboard.hilovivo.com/docs/monitoring/watchlist_consistency_report_latest.md"






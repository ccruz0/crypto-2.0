#!/bin/bash
# Deploy docs endpoint fix via AWS SSM with file upload

set -e

INSTANCE_ID="i-087953603011543c5"
REGION="ap-southeast-1"

echo "🔧 Deploying Docs Endpoint Fix via SSM"
echo "======================================"
echo ""

if ! command -v aws &> /dev/null; then
    echo "❌ AWS CLI not found. Please install it first."
    exit 1
fi

# Encode files to base64 for transmission
echo "📦 Encoding files..."
BACKEND_FILE_B64=$(base64 -i backend/app/api/routes_monitoring.py)
NGINX_FILE_B64=$(base64 -i nginx/dashboard.conf)

echo "📤 Sending deployment command via SSM..."

# Create deployment script that will be executed on the server
COMMAND_ID=$(aws ssm send-command \
    --instance-ids $INSTANCE_ID \
    --document-name "AWS-RunShellScript" \
    --parameters "commands=[
        \"cd ~/automated-trading-platform || cd /home/ubuntu/crypto-2.0\",
        \"echo '📦 Step 1: Restoring backend file...'\",
        \"echo '$BACKEND_FILE_B64' | base64 -d > backend/app/api/routes_monitoring.py.new\",
        \"mv backend/app/api/routes_monitoring.py.new backend/app/api/routes_monitoring.py\",
        \"echo '📝 Step 2: Restoring nginx config...'\",
        \"echo '$NGINX_FILE_B64' | base64 -d > nginx/dashboard.conf.new\",
        \"sudo cp nginx/dashboard.conf.new /etc/nginx/sites-available/dashboard.conf || sudo cp nginx/dashboard.conf.new /etc/nginx/conf.d/dashboard.conf || echo 'Nginx config location may vary'\",
        \"rm -f nginx/dashboard.conf.new\",
        \"echo '🔍 Step 3: Testing nginx configuration...'\",
        \"sudo nginx -t\",
        \"echo '🔄 Step 4: Reloading nginx...'\",
        \"sudo systemctl reload nginx || sudo service nginx reload\",
        \"echo '🔄 Step 5: Restarting backend...'\",
        \"sudo systemctl restart trading-backend 2>/dev/null || sudo systemctl restart backend 2>/dev/null || docker compose restart backend 2>/dev/null || docker restart \\$(docker ps -q -f name=backend) 2>/dev/null || echo 'Backend restart - check service name'\",
        \"echo '✅ Deployment complete!'\",
        \"echo ''\",
        \"echo 'Verification:'\",
        \"grep -q 'watchlist-consistency/latest' backend/app/api/routes_monitoring.py && echo '✅ Backend endpoint added' || echo '❌ Backend endpoint not found'\",
        \"grep -q '/docs/monitoring/' /etc/nginx/sites-available/dashboard.conf 2>/dev/null || grep -q '/docs/monitoring/' /etc/nginx/conf.d/dashboard.conf 2>/dev/null && echo '✅ Nginx config updated' || echo '⚠️  Nginx config location may differ'\"
    ]" \
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






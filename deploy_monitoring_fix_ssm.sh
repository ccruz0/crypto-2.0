#!/bin/bash
# Deploy monitoring endpoint fix via AWS SSM

set -e

INSTANCE_ID="i-087953603011543c5"
REGION="ap-southeast-1"

echo "🚀 Deploying Monitoring Endpoint Fix via SSM"
echo "============================================="
echo ""

if ! command -v aws &> /dev/null; then
    echo "❌ AWS CLI not found. Please install it first."
    exit 1
fi

# Encode file to base64 for transmission using Python (more reliable)
echo "📦 Encoding routes_monitoring.py..."
MONITORING_FILE_B64=$(python3 -c "import base64; print(base64.b64encode(open('backend/app/api/routes_monitoring.py', 'rb').read()).decode())")

echo "📤 Sending deployment command via SSM..."

# Create deployment script that will be executed on the server
COMMAND_ID=$(aws ssm send-command \
    --instance-ids $INSTANCE_ID \
    --document-name "AWS-RunShellScript" \
    --parameters "commands=[
        \"cd ~/automated-trading-platform || cd /home/ubuntu/crypto-2.0\",
        \"echo '📦 Step 1: Restoring routes_monitoring.py file...'\",
        \"echo '$MONITORING_FILE_B64' | base64 -d > backend/app/api/routes_monitoring.py.new\",
        \"mv backend/app/api/routes_monitoring.py.new backend/app/api/routes_monitoring.py\",
        \"echo '🔍 Step 2: Finding backend container...'\",
        \"CONTAINER=\\\$(docker compose --profile aws ps -q backend-aws 2>/dev/null | head -1)\",
        \"if [ -z \\\"\\\$CONTAINER\\\" ]; then CONTAINER=\\\$(docker ps --filter 'name=backend' --format '{{.ID}}' | head -1); fi\",
        \"if [ -n \\\"\\\$CONTAINER\\\" ]; then\",
        \"  echo '✅ Found container: '\\\$CONTAINER\",
        \"  echo '📋 Step 3: Copying file into container...'\",
        \"  docker cp backend/app/api/routes_monitoring.py \\\$CONTAINER:/app/app/api/routes_monitoring.py\",
        \"  echo '🔄 Step 4: Restarting container...'\",
        \"  docker compose --profile aws restart backend-aws 2>/dev/null || docker restart \\\$CONTAINER\",
        \"  echo '⏳ Waiting 10 seconds for backend to start...'\",
        \"  sleep 10\",
        \"  echo '🧪 Step 5: Testing monitoring endpoint...'\",
        \"  if curl -f --connect-timeout 10 http://localhost:8002/api/monitoring/summary >/dev/null 2>&1; then\",
        \"    echo '✅ Monitoring endpoint is healthy!'\",
        \"  else\",
        \"    echo '⚠️  Endpoint check failed, but container is running'\",
        \"  fi\",
        \"  echo ''\",
        \"  echo '📋 Container status:'\",
        \"  docker compose --profile aws ps backend-aws 2>/dev/null || docker ps --filter 'id='\\\$CONTAINER\",
        \"else\",
        \"  echo '❌ Backend container not found'\",
        \"  echo '📋 Available containers:'\",
        \"  docker ps --format 'table {{.Names}}\t{{.Status}}'\",
        \"  exit 1\",
        \"fi\",
        \"echo '✅ Deployment complete!'\"
    ]" \
    --region $REGION \
    --output text \
    --query 'Command.CommandId' 2>&1)

if [[ $COMMAND_ID == Error* ]] || [ -z "$COMMAND_ID" ]; then
    echo "❌ Failed to send command: $COMMAND_ID"
    exit 1
fi

echo "✅ Command ID: $COMMAND_ID"
echo "⏳ Waiting 50 seconds for execution..."
sleep 50

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
echo "🎉 Deployment completed!"
echo ""
echo "💡 Check the dashboard at https://dashboard.hilovivo.com to verify the fix."





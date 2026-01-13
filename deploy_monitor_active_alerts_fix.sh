#!/bin/bash
# Deploy Monitor Active Alerts fix (backend commit 683a137 + frontend commit 39e2e3d) via AWS SSM

set -e

INSTANCE_ID="i-08726dc37133b2454"
REGION="ap-southeast-1"

echo "🚀 Deploying Monitor Active Alerts Fix via SSM"
echo "============================================="
echo "Backend commit: 683a137"
echo "Frontend commit: 39e2e3d"
echo ""

if ! command -v aws &> /dev/null; then
    echo "❌ AWS CLI not found. Please install it first."
    exit 1
fi

# Verify commits exist locally
echo "🔍 Verifying commits exist locally..."
if ! git rev-parse --verify 683a137 >/dev/null 2>&1; then
    echo "❌ Backend commit 683a137 not found locally"
    exit 1
fi

if [ -d "frontend/.git" ]; then
    if ! git -C frontend rev-parse --verify 39e2e3d >/dev/null 2>&1; then
        echo "❌ Frontend commit 39e2e3d not found in frontend submodule"
        exit 1
    fi
    echo "✅ Commits verified"
else
    echo "⚠️  Frontend submodule not found, will deploy backend only"
fi

# Encode backend file to base64
echo "📦 Encoding backend routes_monitoring.py..."
MONITORING_FILE_B64=$(python3 -c "import base64; print(base64.b64encode(open('backend/app/api/routes_monitoring.py', 'rb').read()).decode())")

# Encode frontend file to base64 if available
if [ -f "frontend/src/app/components/MonitoringPanel.tsx" ]; then
    echo "📦 Encoding frontend MonitoringPanel.tsx..."
    FRONTEND_FILE_B64=$(python3 -c "import base64; print(base64.b64encode(open('frontend/src/app/components/MonitoringPanel.tsx', 'rb').read()).decode())")
    DEPLOY_FRONTEND="true"
else
    DEPLOY_FRONTEND="false"
    FRONTEND_FILE_B64=""
fi

echo "📤 Sending deployment command via SSM..."

# Create deployment script
COMMAND_ID=$(aws ssm send-command \
    --instance-ids $INSTANCE_ID \
    --document-name "AWS-RunShellScript" \
    --parameters "commands=[
        \"cd ~/automated-trading-platform || cd /home/ubuntu/automated-trading-platform\",
        \"echo '📦 Step 1: Restoring backend routes_monitoring.py...'\",
        \"echo '$MONITORING_FILE_B64' | base64 -d > backend/app/api/routes_monitoring.py.new\",
        \"mv backend/app/api/routes_monitoring.py.new backend/app/api/routes_monitoring.py\",
        \"if [ '$DEPLOY_FRONTEND' = 'true' ]; then\",
        \"  echo '📦 Step 2: Restoring frontend MonitoringPanel.tsx...'\",
        \"  echo '$FRONTEND_FILE_B64' | base64 -d > frontend/src/app/components/MonitoringPanel.tsx.new\",
        \"  mv frontend/src/app/components/MonitoringPanel.tsx.new frontend/src/app/components/MonitoringPanel.tsx\",
        \"  echo '🔨 Step 3: Rebuilding frontend...'\",
        \"  docker compose --profile aws exec -T frontend-aws npm run build || echo 'Frontend build may have failed'\",
        \"fi\",
        \"echo '🔍 Step 4: Finding backend container...'\",
        \"CONTAINER=\\\$(docker compose --profile aws ps -q backend-aws 2>/dev/null | head -1)\",
        \"if [ -z \\\"\\\$CONTAINER\\\" ]; then CONTAINER=\\\$(docker ps --filter 'name=backend' --format '{{.ID}}' | head -1); fi\",
        \"if [ -n \\\"\\\$CONTAINER\\\" ]; then\",
        \"  echo '✅ Found container: '\\\$CONTAINER\",
        \"  echo '📋 Step 5: Copying backend file into container...'\",
        \"  docker cp backend/app/api/routes_monitoring.py \\\$CONTAINER:/app/app/api/routes_monitoring.py\",
        \"  echo '🔄 Step 6: Restarting backend container...'\",
        \"  docker compose --profile aws restart backend-aws 2>/dev/null || docker restart \\\$CONTAINER\",
        \"  echo '⏳ Waiting 15 seconds for backend to start...'\",
        \"  sleep 15\",
        \"  echo '🧪 Step 7: Testing monitoring endpoint...'\",
        \"  curl -s --connect-timeout 10 http://localhost:8000/api/monitoring/summary | head -100 || echo 'Endpoint check failed'\",
        \"  echo ''\",
        \"  echo '📋 Container status:'\",
        \"  docker compose --profile aws ps backend-aws 2>/dev/null || docker ps --filter 'id='\\\$CONTAINER\",
        \"  echo ''\",
        \"  echo '📊 Git commit verification:'\",
        \"  git -C backend log -1 --oneline || echo 'Could not check backend commit'\",
        \"  if [ -d frontend/.git ]; then git -C frontend log -1 --oneline || echo 'Could not check frontend commit'; fi\",
        \"else\",
        \"  echo '❌ Backend container not found'\",
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
echo "⏳ Waiting 60 seconds for execution..."
sleep 60

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
echo "💡 Next: Run verification script to check data and take screenshots"

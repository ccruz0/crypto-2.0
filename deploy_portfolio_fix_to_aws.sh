#!/bin/bash
# Deploy Portfolio Fix to AWS via SSM
# Uses normal deployment path (git pull + docker compose)

set -e

INSTANCE_ID="i-08726dc37133b2454"
REGION="ap-southeast-1"

echo "🚀 Deploying Portfolio Fix to AWS"
echo "================================="
echo ""

# Check AWS CLI
if ! command -v aws &> /dev/null; then
    echo "❌ AWS CLI is not installed"
    exit 1
fi

echo "📋 Step 1: Checking current state on AWS..."
echo ""

CHECK_CMD=$(aws ssm send-command \
    --instance-ids "$INSTANCE_ID" \
    --region "$REGION" \
    --document-name "AWS-RunShellScript" \
    --parameters 'commands=[
        "cd ~/automated-trading-platform || cd /home/ubuntu/automated-trading-platform",
        "echo \"=== Current Backend Status ===\"",
        "docker compose --profile aws ps backend-aws 2>/dev/null || docker ps --filter \"name=backend-aws\"",
        "echo \"\"",
        "echo \"=== Port 8002 Check ===\"",
        "sudo lsof -nP -iTCP:8002 -sTCP:LISTEN 2>/dev/null || echo \"Could not check port 8002\""
    ]' \
    --query 'Command.CommandId' \
    --output text)

sleep 5

CHECK_OUTPUT=$(aws ssm get-command-invocation \
    --instance-id "$INSTANCE_ID" \
    --region "$REGION" \
    --command-id "$CHECK_CMD" \
    --query 'StandardOutputContent' \
    --output text 2>/dev/null)

echo "$CHECK_OUTPUT"
echo ""

echo "📦 Step 2: Deploying fix via git pull + docker compose..."
echo ""

DEPLOY_CMD=$(aws ssm send-command \
    --instance-ids "$INSTANCE_ID" \
    --region "$REGION" \
    --document-name "AWS-RunShellScript" \
    --parameters 'commands=[
        "cd ~/automated-trading-platform || cd /home/ubuntu/automated-trading-platform",
        "echo \"📥 Pulling latest code...\"",
        "git pull origin main || echo \"Git pull failed, continuing...\"",
        "echo \"\"",
        "echo \"🔨 Building backend image...\"",
        "docker compose --profile aws build backend-aws || echo \"Build failed, trying restart only...\"",
        "echo \"\"",
        "echo \"🔄 Restarting backend-aws service...\"",
        "docker compose --profile aws up -d --build backend-aws || docker compose --profile aws restart backend-aws",
        "echo \"\"",
        "echo \"⏳ Waiting for backend to be ready...\"",
        "sleep 15",
        "echo \"\"",
        "echo \"✅ Checking backend status...\"",
        "docker compose --profile aws ps backend-aws",
        "echo \"\"",
        "echo \"🧪 Testing health endpoint...\"",
        "curl -s http://localhost:8002/api/health || echo \"Health check failed\""
    ]' \
    --query 'Command.CommandId' \
    --output text)

echo "✅ Deploy command sent (ID: $DEPLOY_CMD)"
echo "⏳ Waiting for deployment (60-90 seconds)..."

sleep 60

DEPLOY_OUTPUT=$(aws ssm get-command-invocation \
    --instance-id "$INSTANCE_ID" \
    --region "$REGION" \
    --command-id "$DEPLOY_CMD" \
    --query 'StandardOutputContent' \
    --output text 2>/dev/null)

echo "$DEPLOY_OUTPUT"
echo ""

echo "🧪 Step 3: Verifying deployment..."
echo ""

# Wait a bit more for service to be fully ready
sleep 10

echo "Testing whoami endpoint..."
WHOAMI=$(curl -sS --max-time 10 "http://localhost:8002/api/diagnostics/whoami" 2>/dev/null || echo "FAILED")
if echo "$WHOAMI" | grep -q "service_info"; then
    echo "✅ whoami endpoint exists!"
    echo "$WHOAMI" | python3 -m json.tool 2>/dev/null | head -40
else
    echo "⚠️  whoami endpoint still not found"
    echo "$WHOAMI"
fi
echo ""

echo "Testing portfolio snapshot..."
SNAPSHOT=$(curl -sS --max-time 15 "http://localhost:8002/api/portfolio/snapshot?exchange=CRYPTO_COM" 2>/dev/null || echo "FAILED")
if [ "$SNAPSHOT" != "FAILED" ]; then
    OK=$(echo "$SNAPSHOT" | python3 -c "import sys, json; d=json.load(sys.stdin); print(d.get('ok', False))" 2>/dev/null || echo "false")
    SOURCE=$(echo "$SNAPSHOT" | python3 -c "import sys, json; d=json.load(sys.stdin); print(d.get('portfolio_source', 'N/A'))" 2>/dev/null || echo "N/A")
    POSITIONS=$(echo "$SNAPSHOT" | python3 -c "import sys, json; d=json.load(sys.stdin); print(len(d.get('positions', [])))" 2>/dev/null || echo "0")
    ERRORS=$(echo "$SNAPSHOT" | python3 -c "import sys, json; d=json.load(sys.stdin); errs=d.get('errors', []); print('; '.join(errs[:2]) if errs else 'none')" 2>/dev/null || echo "unknown")
    
    echo "Result:"
    echo "  ok: $OK"
    echo "  portfolio_source: $SOURCE"
    echo "  positions: $POSITIONS"
    echo "  errors: $ERRORS"
    echo ""
    
    if [ "$OK" = "True" ] && [ "$SOURCE" = "crypto_com" ] && [ "$POSITIONS" -gt 0 ]; then
        echo "✅ Portfolio snapshot is working correctly!"
        echo ""
        echo "Sample response:"
        echo "$SNAPSHOT" | python3 -m json.tool 2>/dev/null | head -60
    elif [ "$OK" = "True" ] && [ "$SOURCE" = "crypto_com" ]; then
        echo "⚠️  Portfolio snapshot works but no positions (empty account?)"
        echo "$SNAPSHOT" | python3 -m json.tool 2>/dev/null | head -60
    elif echo "$ERRORS" | grep -q "40101"; then
        echo "❌ Auth error 40101 - checking credential sources..."
        echo "$SNAPSHOT" | python3 -m json.tool 2>/dev/null | head -80
    else
        echo "⚠️  Portfolio snapshot returned but not fully working"
        echo "$SNAPSHOT" | python3 -m json.tool 2>/dev/null | head -80
    fi
else
    echo "❌ Portfolio snapshot endpoint failed"
    echo "$SNAPSHOT"
fi

echo ""
echo "✅ Deployment complete!"
echo ""
echo "📋 Summary:"
echo "  - Instance: $INSTANCE_ID"
echo "  - Service: backend-aws (docker compose --profile aws)"
echo "  - Port: 8002"
echo ""
echo "🧪 Verification commands:"
echo "  curl -sS http://localhost:8002/api/diagnostics/whoami | python3 -m json.tool"
echo "  curl -sS 'http://localhost:8002/api/portfolio/snapshot?exchange=CRYPTO_COM' | python3 -m json.tool | head -80"


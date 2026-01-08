#!/bin/bash
# Deploy Telegram Health Check Fix to AWS
# This script deploys the updated system_health.py file to AWS

set -e

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

echo "=========================================="
echo "Deploy Telegram Health Check Fix"
echo "=========================================="
echo ""

# Configuration
EC2_HOST="${EC2_HOST:-47.130.143.159}"
EC2_USER="${EC2_USER:-ubuntu}"
PROJECT_DIR="${PROJECT_DIR:-automated-trading-platform}"

# Check if we have SSH access
echo "🔍 Checking SSH access to AWS..."
if ! ssh -o ConnectTimeout=5 -o BatchMode=yes "${EC2_USER}@${EC2_HOST}" exit 2>/dev/null; then
    echo -e "${YELLOW}⚠️  SSH key-based authentication not configured${NC}"
    echo "   You may need to use: ssh -i your-key.pem ${EC2_USER}@${EC2_HOST}"
    echo ""
    read -p "Continue with manual SSH? (y/n) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
fi

echo -e "${GREEN}✅ SSH access confirmed${NC}"
echo ""

# File to deploy
SOURCE_FILE="backend/app/services/system_health.py"
TARGET_PATH="backend/app/services/system_health.py"

echo "📋 Deployment plan:"
echo "   Source: ${SOURCE_FILE}"
echo "   Target: ${EC2_USER}@${EC2_HOST}:~/${PROJECT_DIR}/${TARGET_PATH}"
echo ""

# Verify source file exists
if [ ! -f "$SOURCE_FILE" ]; then
    echo -e "${RED}❌ ERROR: Source file not found: ${SOURCE_FILE}${NC}"
    exit 1
fi

echo -e "${GREEN}✅ Source file found${NC}"
echo ""

# Deploy file
echo "📤 Deploying file to AWS..."
scp "${SOURCE_FILE}" "${EC2_USER}@${EC2_HOST}:~/${PROJECT_DIR}/${TARGET_PATH}" || {
    echo -e "${RED}❌ ERROR: Failed to copy file${NC}"
    exit 1
}

echo -e "${GREEN}✅ File deployed${NC}"
echo ""

# Restart backend service
echo "🔄 Restarting backend service..."
ssh "${EC2_USER}@${EC2_HOST}" << 'ENDSSH'
cd ~/automated-trading-platform
echo "Stopping backend..."
docker compose --profile aws stop backend-aws || true
echo "Starting backend..."
docker compose --profile aws up -d backend-aws
echo "Waiting for service to start..."
sleep 10
echo "Checking service status..."
docker compose --profile aws ps backend-aws
ENDSSH

echo ""
echo "⏳ Waiting for backend to be ready..."
sleep 15

# Verify health check
echo ""
echo "🏥 Verifying health check..."
HEALTH_RESPONSE=$(ssh "${EC2_USER}@${EC2_HOST}" "curl -s http://localhost:8002/api/health/system" || echo "")

if [ -z "$HEALTH_RESPONSE" ]; then
    echo -e "${YELLOW}⚠️  Health endpoint not responding yet${NC}"
    echo "   Service may need more time to start"
else
    TELEGRAM_STATUS=$(echo "$HEALTH_RESPONSE" | python3 -c "import sys, json; data=json.load(sys.stdin); print(data.get('telegram', {}).get('status', 'UNKNOWN'))" 2>/dev/null || echo "UNKNOWN")
    
    if [ "$TELEGRAM_STATUS" = "PASS" ] || [ "$TELEGRAM_STATUS" = "FAIL" ]; then
        echo -e "${GREEN}✅ Health check responding${NC}"
        echo ""
        echo "Telegram status: $TELEGRAM_STATUS"
        echo ""
        echo "Full Telegram health:"
        echo "$HEALTH_RESPONSE" | python3 -m json.tool | grep -A 10 '"telegram"' || echo "$HEALTH_RESPONSE"
    else
        echo -e "${YELLOW}⚠️  Health check responding but status unclear${NC}"
        echo "Response: $HEALTH_RESPONSE"
    fi
fi

echo ""
echo "=========================================="
echo -e "${GREEN}✅ Deployment Complete${NC}"
echo "=========================================="
echo ""
echo "Next steps:"
echo "1. Verify health: curl -s https://dashboard.hilovivo.com/api/health/system | jq .telegram"
echo "2. Configure Telegram (if not done): ./scripts/configure_telegram_aws.sh"
echo "3. Check logs: ssh ${EC2_USER}@${EC2_HOST} 'docker compose --profile aws logs --tail 50 backend-aws'"
echo ""


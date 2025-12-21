#!/bin/bash
# Deployment script for direct AWS Elastic IP connection migration
# This script completes the deployment after files are synced

set -e

EC2_HOST="47.130.143.159"
EC2_USER="ubuntu"
PROJECT_DIR="automated-trading-platform"

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

echo -e "${GREEN}=== Direct Connection Migration Deployment ===${NC}"
echo ""

# Check SSH connection
echo -e "${GREEN}[1/5]${NC} Testing SSH connection..."
if ! ssh -o ConnectTimeout=10 -o StrictHostKeyChecking=no "$EC2_USER@$EC2_HOST" "echo 'Connected'" > /dev/null 2>&1; then
    echo -e "${RED}❌ Cannot connect to $EC2_HOST${NC}"
    exit 1
fi
echo -e "${GREEN}✅ Connected${NC}"
echo ""

# Deploy on AWS
echo -e "${GREEN}[2/5]${NC} Deploying services on AWS..."
ssh -o StrictHostKeyChecking=no "$EC2_USER@$EC2_HOST" << 'DEPLOY_SCRIPT'
cd ~/automated-trading-platform

echo "📦 Loading Docker images (if any)..."
if [ -f "backend-aws.tar.gz" ]; then
    docker load < backend-aws.tar.gz || true
fi
if [ -f "frontend-aws.tar.gz" ]; then
    docker load < frontend-aws.tar.gz || true
fi

echo "🛑 Stopping existing services..."
docker compose --profile aws down || true

echo "🏗️  Building services..."
docker compose --profile aws build backend-aws market-updater-aws || true

echo "🚀 Starting services..."
docker compose --profile aws up -d db backend-aws market-updater-aws

echo "⏳ Waiting for services to start..."
sleep 20

echo "📊 Service status:"
docker compose --profile aws ps

echo ""
echo "🔍 Backend logs (last 30 lines):"
docker compose --profile aws logs backend-aws --tail=30 | grep -E "CryptoComTradeClient|USE_CRYPTO_PROXY|base URL|PROXY" || docker compose --profile aws logs backend-aws --tail=30

echo ""
echo "✅ Deployment script completed on server"
DEPLOY_SCRIPT

echo ""
echo -e "${GREEN}[3/5]${NC} Verifying deployment..."
ssh -o StrictHostKeyChecking=no "$EC2_USER@$EC2_HOST" << 'VERIFY_SCRIPT'
cd ~/automated-trading-platform

echo "Checking backend-aws environment variables:"
docker compose --profile aws exec -T backend-aws env | grep -E "USE_CRYPTO_PROXY|EXCHANGE_CUSTOM_BASE_URL|CRYPTO_REST_BASE|LIVE_TRADING" | sort

echo ""
echo "Testing backend health:"
curl -f http://localhost:8002/health 2>/dev/null && echo "✅ Backend health check passed" || echo "⚠️  Backend health check failed"
VERIFY_SCRIPT

echo ""
echo -e "${GREEN}[4/5]${NC} Checking service dependencies..."
ssh -o StrictHostKeyChecking=no "$EC2_USER@$EC2_HOST" "cd ~/automated-trading-platform && docker compose --profile aws config | grep -A 10 'backend-aws:' | grep -A 5 'depends_on:'"

echo ""
echo -e "${GREEN}[5/5]${NC} Final verification..."
echo ""
echo "Expected configuration:"
echo "  ✓ USE_CRYPTO_PROXY=false"
echo "  ✓ EXCHANGE_CUSTOM_BASE_URL=https://api.crypto.com/exchange/v1"
echo "  ✓ Backend-aws should only depend on 'db' (not gluetun)"
echo ""
echo -e "${GREEN}=== Deployment Complete ===${NC}"
echo ""
echo "Next steps:"
echo "1. Monitor backend logs: ssh $EC2_USER@$EC2_HOST 'cd ~/$PROJECT_DIR && docker compose --profile aws logs -f backend-aws'"
echo "2. Verify direct connection: Check logs for 'Using base URL: https://api.crypto.com/exchange/v1'"
echo "3. Test API endpoints that use Crypto.com Exchange"





















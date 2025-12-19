#!/bin/bash
# Deploy and Verification Script
set -e

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}Deploy and Verification Script${NC}"
echo -e "${GREEN}========================================${NC}"

EC2_HOST="54.254.150.31"
EC2_USER="ubuntu"

echo -e "${YELLOW}[1/4] Testing AWS connection...${NC}"
if ssh -o ConnectTimeout=5 -o StrictHostKeyChecking=no "$EC2_USER@$EC2_HOST" "echo 'Connected'" > /dev/null 2>&1; then
    echo -e "${GREEN}✅ AWS connection successful${NC}"
else
    EC2_HOST="175.41.189.249"
    if ssh -o ConnectTimeout=5 -o StrictHostKeyChecking=no "$EC2_USER@$EC2_HOST" "echo 'Connected'" > /dev/null 2>&1; then
        echo -e "${GREEN}✅ AWS connection successful (alternative)${NC}"
    else
        echo -e "${RED}❌ Cannot connect to AWS${NC}"
        exit 1
    fi
fi

echo -e "${YELLOW}[2/4] Deploying to AWS...${NC}"
ssh "$EC2_USER@$EC2_HOST" 'cd ~/automated-trading-platform && git pull && docker compose --profile aws build --no-cache backend-aws market-updater-aws && docker compose --profile aws up -d backend-aws market-updater-aws && sleep 15 && docker compose --profile aws ps'

echo -e "${GREEN}✅ Deploy completed${NC}"

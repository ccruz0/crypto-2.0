#!/bin/bash
# Quick deployment script for Telegram /start fix on AWS

set -e

echo "=========================================="
echo "Telegram /start Fix - AWS Deployment"
echo "=========================================="
echo ""

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Check if we're on AWS or local
if [ -f "/.dockerenv" ] || [ -n "$AWS_EXECUTION_ENV" ]; then
    echo -e "${BLUE}Detected AWS environment${NC}"
    ENV_TYPE="aws"
else
    echo -e "${YELLOW}Detected local environment${NC}"
    ENV_TYPE="local"
fi

echo ""
echo -e "${YELLOW}Step 1: Checking git status...${NC}"
if [ -d ".git" ]; then
    git_status=$(git status --porcelain)
    if [ -z "$git_status" ]; then
        echo -e "   ${GREEN}✅ Working directory clean${NC}"
    else
        echo -e "   ${YELLOW}⚠️  Uncommitted changes detected:${NC}"
        echo "$git_status" | sed 's/^/      /'
        read -p "   Continue anyway? (y/n) " -n 1 -r
        echo
        if [[ ! $REPLY =~ ^[Yy]$ ]]; then
            exit 1
        fi
    fi
    
    # Show last commit
    echo ""
    echo -e "${YELLOW}Last commit:${NC}"
    git log -1 --oneline | sed 's/^/   /'
else
    echo -e "   ${YELLOW}⚠️  Not a git repository, skipping git checks${NC}"
fi

echo ""
echo -e "${YELLOW}Step 2: Checking Docker Compose...${NC}"
if command -v docker-compose &> /dev/null || command -v docker &> /dev/null; then
    echo -e "   ${GREEN}✅ Docker available${NC}"
    
    # Check if containers are running
    if docker compose ps 2>/dev/null | grep -q "backend-aws.*Up"; then
        echo -e "   ${GREEN}✅ backend-aws container is running${NC}"
    else
        echo -e "   ${YELLOW}⚠️  backend-aws container not running${NC}"
        echo -e "   ${BLUE}   Start with: docker compose --profile aws up -d backend-aws${NC}"
    fi
else
    echo -e "   ${RED}❌ Docker not available${NC}"
    exit 1
fi

echo ""
echo -e "${YELLOW}Step 3: Deployment options...${NC}"
echo ""
echo "Choose deployment method:"
echo "  1) Rebuild and restart backend-aws (recommended)"
echo "  2) Just restart backend-aws (if code already updated)"
echo "  3) Run diagnostics only (no deployment)"
echo "  4) Exit"
echo ""
read -p "Enter choice [1-4]: " choice

case $choice in
    1)
        echo ""
        echo -e "${YELLOW}Rebuilding and restarting backend-aws...${NC}"
        docker compose --profile aws up -d --build backend-aws
        echo -e "${GREEN}✅ Rebuild complete${NC}"
        ;;
    2)
        echo ""
        echo -e "${YELLOW}Restarting backend-aws...${NC}"
        docker compose --profile aws restart backend-aws
        echo -e "${GREEN}✅ Restart complete${NC}"
        ;;
    3)
        echo ""
        echo -e "${YELLOW}Running diagnostics only...${NC}"
        docker compose --profile aws exec backend-aws python -m tools.telegram_diag || {
            echo -e "${RED}❌ Diagnostics failed - container may not be ready${NC}"
            exit 1
        }
        exit 0
        ;;
    4)
        echo "Exiting..."
        exit 0
        ;;
    *)
        echo -e "${RED}Invalid choice${NC}"
        exit 1
        ;;
esac

echo ""
echo -e "${YELLOW}Step 4: Waiting for container to be ready...${NC}"
sleep 5

echo ""
echo -e "${YELLOW}Step 5: Checking container health...${NC}"
if docker compose --profile aws ps | grep -q "backend-aws.*Up"; then
    echo -e "   ${GREEN}✅ Container is running${NC}"
else
    echo -e "   ${RED}❌ Container failed to start${NC}"
    echo -e "   ${BLUE}Check logs: docker compose --profile aws logs backend-aws${NC}"
    exit 1
fi

echo ""
echo -e "${YELLOW}Step 6: Running Telegram diagnostics...${NC}"
if docker compose --profile aws exec backend-aws python -m tools.telegram_diag 2>/dev/null; then
    echo -e "   ${GREEN}✅ Diagnostics completed${NC}"
else
    echo -e "   ${YELLOW}⚠️  Diagnostics tool not available or container not ready${NC}"
    echo -e "   ${BLUE}   This is OK if container just started - wait a few seconds and run manually:${NC}"
    echo -e "   ${BLUE}   docker compose --profile aws exec backend-aws python -m tools.telegram_diag${NC}"
fi

echo ""
echo -e "${YELLOW}Step 7: Checking startup logs...${NC}"
echo ""
echo -e "${BLUE}Recent startup logs (last 20 lines):${NC}"
docker compose --profile aws logs --tail=20 backend-aws | grep -i "TG\|telegram\|startup\|webhook" || {
    echo "   (No Telegram-related logs found in last 20 lines)"
}

echo ""
echo -e "${GREEN}=========================================="
echo "✅ Deployment complete!"
echo "==========================================${NC}"
echo ""
echo "Next steps:"
echo "1. Monitor logs: docker compose --profile aws logs -f backend-aws | grep -i TG"
echo "2. Run diagnostics: docker compose --profile aws exec backend-aws python -m tools.telegram_diag"
echo "3. Test /start command in Telegram"
echo "4. Check for:"
echo "   - 'Webhook deleted successfully' or 'No webhook configured'"
echo "   - 'Poller lock acquired'"
echo "   - 'Processing /start command' when you send /start"
echo ""


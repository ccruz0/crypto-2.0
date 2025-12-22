#!/bin/bash
# Test script for Telegram /start fix deployment

set -e

echo "=========================================="
echo "Telegram /start Fix - Deployment Test"
echo "=========================================="
echo ""

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# Check if we're in the right directory
if [ ! -f "docker-compose.yml" ]; then
    echo -e "${RED}❌ Error: docker-compose.yml not found. Run this from the project root.${NC}"
    exit 1
fi

echo -e "${YELLOW}1. Checking file syntax...${NC}"
cd backend

# Check Python syntax
echo "   Checking telegram_commands.py..."
python3 -m py_compile app/services/telegram_commands.py && echo -e "   ${GREEN}✅ OK${NC}" || { echo -e "   ${RED}❌ Syntax error${NC}"; exit 1; }

echo "   Checking telegram_diag.py..."
python3 -m py_compile tools/telegram_diag.py && echo -e "   ${GREEN}✅ OK${NC}" || { echo -e "   ${RED}❌ Syntax error${NC}"; exit 1; }

echo "   Checking test_telegram_start.py..."
python3 -m py_compile app/tests/test_telegram_start.py && echo -e "   ${GREEN}✅ OK${NC}" || { echo -e "   ${RED}❌ Syntax error${NC}"; exit 1; }

cd ..

echo ""
echo -e "${YELLOW}2. Checking for required files...${NC}"

files=(
    "backend/app/services/telegram_commands.py"
    "backend/tools/telegram_diag.py"
    "backend/app/tests/test_telegram_start.py"
    "docs/telegram/telegram_start_not_responding_report.md"
)

for file in "${files[@]}"; do
    if [ -f "$file" ]; then
        echo -e "   ${GREEN}✅${NC} $file"
    else
        echo -e "   ${RED}❌ Missing: $file${NC}"
        exit 1
    fi
done

echo ""
echo -e "${YELLOW}3. Checking key changes in telegram_commands.py...${NC}"

# Check for diagnostics mode
if grep -q "TELEGRAM_DIAGNOSTICS" backend/app/services/telegram_commands.py; then
    echo -e "   ${GREEN}✅${NC} Diagnostics mode implemented"
else
    echo -e "   ${RED}❌ Diagnostics mode not found${NC}"
    exit 1
fi

# Check for allowed_updates
if grep -q '"allowed_updates".*my_chat_member' backend/app/services/telegram_commands.py; then
    echo -e "   ${GREEN}✅${NC} allowed_updates includes my_chat_member"
else
    echo -e "   ${RED}❌ allowed_updates fix not found${NC}"
    exit 1
fi

# Check for my_chat_member handling
if grep -q "my_chat_member = update.get" backend/app/services/telegram_commands.py; then
    echo -e "   ${GREEN}✅${NC} my_chat_member handling added"
else
    echo -e "   ${RED}❌ my_chat_member handling not found${NC}"
    exit 1
fi

# Check for webhook deletion
if grep -q "deleteWebhook" backend/app/services/telegram_commands.py; then
    echo -e "   ${GREEN}✅${NC} Webhook deletion implemented"
else
    echo -e "   ${RED}❌ Webhook deletion not found${NC}"
    exit 1
fi

echo ""
echo -e "${YELLOW}4. Testing CLI tool import...${NC}"
cd backend
if python3 -c "import sys; sys.path.insert(0, '.'); from tools.telegram_diag import main; print('OK')" 2>/dev/null; then
    echo -e "   ${GREEN}✅${NC} CLI tool imports successfully"
else
    echo -e "   ${YELLOW}⚠️${NC}  CLI tool import check (may need dependencies)"
fi
cd ..

echo ""
echo -e "${YELLOW}5. Checking docker-compose configuration...${NC}"
if grep -q "backend-aws" docker-compose.yml; then
    echo -e "   ${GREEN}✅${NC} backend-aws service found"
else
    echo -e "   ${RED}❌ backend-aws service not found${NC}"
    exit 1
fi

echo ""
echo -e "${GREEN}=========================================="
echo "✅ All pre-deployment checks passed!"
echo "==========================================${NC}"
echo ""
echo "Next steps:"
echo "1. Review changes: git diff backend/app/services/telegram_commands.py"
echo "2. Test locally: docker compose --profile local up backend"
echo "3. Test in AWS: docker compose --profile aws up backend-aws"
echo "4. Run diagnostics: docker compose exec backend-aws python -m tools.telegram_diag"
echo "5. Test /start command in Telegram"
echo ""


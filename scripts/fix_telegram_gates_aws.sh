#!/bin/bash
# Fix script to enable Telegram health gates on AWS
# Run this on AWS: ssh ubuntu@47.130.143.159 "cd ~/automated-trading-platform && bash scripts/fix_telegram_gates_aws.sh"

set -euo pipefail

cd "$(git rev-parse --show-toplevel 2>/dev/null || echo /home/ubuntu/automated-trading-platform)"

echo "=========================================="
echo "Telegram Health Gates Fix"
echo "=========================================="
echo ""

# Discover backend container
BACKEND_CONTAINER=""
if command -v docker > /dev/null 2>&1 && docker compose --profile aws ps backend-aws > /dev/null 2>&1; then
    BACKEND_CONTAINER="backend-aws"
elif docker ps --filter "name=backend-aws" --format "{{.Names}}" | grep -q .; then
    BACKEND_CONTAINER=$(docker ps --filter "name=backend-aws" --format "{{.Names}}" | head -1)
else
    echo "❌ ERROR: backend-aws container not found"
    exit 1
fi

# Function to exec in backend container
exec_backend() {
    if [ "$BACKEND_CONTAINER" == "backend-aws" ]; then
        docker compose --profile aws exec -T backend-aws "$@"
    else
        docker exec -i "$BACKEND_CONTAINER" "$@"
    fi
}

FIXES_APPLIED=0
CREDENTIALS_MISSING=false

# Fix Gate 1: RUN_TELEGRAM
echo "=== Fixing Gate 1: RUN_TELEGRAM ==="
RUN_TELEGRAM=$(exec_backend env | grep "^RUN_TELEGRAM=" | cut -d= -f2 || echo "")

# Determine env file to edit
ENV_FILE=""
if [ -f ".env.aws" ]; then
    ENV_FILE=".env.aws"
elif [ -f "./secrets/runtime.env" ]; then
    ENV_FILE="./secrets/runtime.env"
elif [ -f ".env" ]; then
    ENV_FILE=".env"
else
    echo "  ⚠️  No .env.aws, secrets/runtime.env, or .env found"
    echo "     Cannot automatically fix RUN_TELEGRAM"
    ENV_FILE=""
fi

if [ -z "$RUN_TELEGRAM" ]; then
    if [ -n "$ENV_FILE" ]; then
        if grep -q "^RUN_TELEGRAM=" "$ENV_FILE" 2>/dev/null; then
            echo "  Updating RUN_TELEGRAM in $ENV_FILE..."
            sed -i.bak "s/^RUN_TELEGRAM=.*/RUN_TELEGRAM=true/" "$ENV_FILE"
        else
            echo "  Adding RUN_TELEGRAM=true to $ENV_FILE..."
            echo "RUN_TELEGRAM=true" >> "$ENV_FILE"
        fi
        FIXES_APPLIED=$((FIXES_APPLIED + 1))
        echo "  ✅ Added RUN_TELEGRAM=true to $ENV_FILE"
    else
        echo "  ❌ Cannot fix: No env file found"
    fi
else
    RUN_TELEGRAM_LOWER=$(echo "$RUN_TELEGRAM" | tr '[:upper:]' '[:lower:]')
    if [[ "$RUN_TELEGRAM_LOWER" == "true" ]] || [[ "$RUN_TELEGRAM_LOWER" == "1" ]] || [[ "$RUN_TELEGRAM_LOWER" == "yes" ]]; then
        echo "  ✅ RUN_TELEGRAM already set correctly"
    else
        if [ -n "$ENV_FILE" ]; then
            echo "  Updating RUN_TELEGRAM in $ENV_FILE..."
            sed -i.bak "s/^RUN_TELEGRAM=.*/RUN_TELEGRAM=true/" "$ENV_FILE"
            FIXES_APPLIED=$((FIXES_APPLIED + 1))
            echo "  ✅ Updated RUN_TELEGRAM=true in $ENV_FILE"
        else
            echo "  ❌ Cannot fix: No env file found"
        fi
    fi
fi
echo ""

# Fix Gate 2: Kill Switch
echo "=== Fixing Gate 2: Kill Switch (tg_enabled_aws) ==="
KILL_SWITCH_RESULT=$(exec_backend python3 << 'PYEOF'
import sys
try:
    from app.database import SessionLocal
    from app.models.trading_settings import TradingSettings
    
    db = SessionLocal()
    try:
        setting = db.query(TradingSettings).filter(
            TradingSettings.setting_key == 'tg_enabled_aws'
        ).first()
        
        if setting:
            current_value = setting.setting_value.lower()
            if current_value == "true":
                print("already_true")
                sys.exit(0)
            else:
                setting.setting_value = 'true'
                db.commit()
                print("updated_to_true")
                sys.exit(0)
        else:
            new_setting = TradingSettings(setting_key='tg_enabled_aws', setting_value='true')
            db.add(new_setting)
            db.commit()
            print("created_true")
            sys.exit(0)
    except Exception as e:
        print(f"error:{e}")
        db.rollback()
        sys.exit(1)
    finally:
        db.close()
except Exception as e:
    print(f"error:{e}")
    sys.exit(1)
PYEOF
)
KILL_SWITCH_EXIT=$?

if [ $KILL_SWITCH_EXIT -eq 0 ]; then
    if [ "$KILL_SWITCH_RESULT" == "already_true" ]; then
        echo "  ✅ Kill switch already enabled"
    elif [ "$KILL_SWITCH_RESULT" == "updated_to_true" ]; then
        echo "  ✅ Updated kill switch to true"
        FIXES_APPLIED=$((FIXES_APPLIED + 1))
    elif [ "$KILL_SWITCH_RESULT" == "created_true" ]; then
        echo "  ✅ Created kill switch and set to true"
        FIXES_APPLIED=$((FIXES_APPLIED + 1))
    fi
else
    echo "  ❌ Failed to set kill switch: $KILL_SWITCH_RESULT"
fi
echo ""

# Check Gate 3: Bot Token (DO NOT OVERWRITE)
echo "=== Checking Gate 3: Bot Token ==="
BOT_TOKEN=$(exec_backend env | grep -E "^TELEGRAM_BOT_TOKEN(_AWS)?=" | head -1 | cut -d= -f2 || echo "")
if [ -z "$BOT_TOKEN" ]; then
    echo "  ❌ Bot token not set - MANUAL ACTION REQUIRED"
    echo "     Add TELEGRAM_BOT_TOKEN or TELEGRAM_BOT_TOKEN_AWS to .env.aws"
    CREDENTIALS_MISSING=true
else
    if [ ${#BOT_TOKEN} -gt 10 ]; then
        TOKEN_MASKED="${BOT_TOKEN:0:6}...${BOT_TOKEN: -4}"
    else
        TOKEN_MASKED="***MASKED***"
    fi
    echo "  ✅ Bot token already set (${TOKEN_MASKED})"
fi
echo ""

# Check Gate 4: Chat ID (DO NOT OVERWRITE)
echo "=== Checking Gate 4: Chat ID ==="
CHAT_ID=$(exec_backend env | grep -E "^TELEGRAM_CHAT_ID(_AWS)?=" | head -1 | cut -d= -f2 || echo "")
if [ -z "$CHAT_ID" ]; then
    echo "  ❌ Chat ID not set - MANUAL ACTION REQUIRED"
    echo "     Add TELEGRAM_CHAT_ID or TELEGRAM_CHAT_ID_AWS to .env.aws"
    CREDENTIALS_MISSING=true
else
    echo "  ✅ Chat ID already set ($CHAT_ID)"
fi
echo ""

echo "=========================================="
echo "Summary"
echo "=========================================="
echo "Fixes applied: $FIXES_APPLIED"
echo ""

if [ "$CREDENTIALS_MISSING" = "true" ]; then
    echo "❌ ERROR: Credentials missing - cannot proceed"
    echo ""
    echo "Manual steps required:"
    echo "  1. Edit .env.aws:"
    echo "     nano .env.aws"
    echo "  2. Add missing credentials:"
    echo "     TELEGRAM_BOT_TOKEN=<your_token>"
    echo "     TELEGRAM_CHAT_ID=<your_chat_id>"
    echo "  3. Restart backend:"
    echo "     docker compose --profile aws restart backend-aws"
    exit 1
fi

if [ $FIXES_APPLIED -gt 0 ]; then
    echo "⚠️  Restarting backend to apply changes..."
    if [ "$BACKEND_CONTAINER" == "backend-aws" ]; then
        docker compose --profile aws restart backend-aws
    else
        docker restart "$BACKEND_CONTAINER"
    fi
    echo "  ✅ Backend restarted"
    echo ""
    echo "Waiting for backend to be healthy (up to 2 minutes)..."
    timeout 120 bash -c "until exec_backend python3 -c \"import urllib.request; urllib.request.urlopen('http://localhost:8002/ping_fast', timeout=3)\" 2>/dev/null; do sleep 2; done" && echo "✅ Backend is healthy" || echo "⚠️  Backend health check timeout"
    echo ""
fi

echo "Run verification:"
echo "  bash scripts/verify_telegram_green_aws.sh"
echo ""
echo "Or check health endpoint:"
echo "  curl -s http://localhost:8002/api/health/system | grep -o '\"telegram\":{[^}]*}'"

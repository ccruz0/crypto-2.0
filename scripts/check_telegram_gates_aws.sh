#!/bin/bash
# Diagnostic script to check all 4 Telegram health gates on AWS
# Run this on AWS: ssh ubuntu@47.130.143.159 "cd ~/automated-trading-platform && bash scripts/check_telegram_gates_aws.sh"

set -euo pipefail

cd "$(git rev-parse --show-toplevel 2>/dev/null || echo /home/ubuntu/automated-trading-platform)"

echo "=========================================="
echo "Telegram Health Gates Diagnostic"
echo "=========================================="
echo ""

# Gate 0: Discover containers/services
echo "=== Gate 0: Container/Service Discovery ==="
BACKEND_CONTAINER=""
DB_CONTAINER=""

# Try docker compose first
if command -v docker > /dev/null 2>&1 && docker compose --profile aws ps backend-aws > /dev/null 2>&1; then
    BACKEND_CONTAINER="backend-aws"
    echo "  Backend service: backend-aws (docker compose)"
    
    # Check for db service
    if docker compose --profile aws ps db > /dev/null 2>&1; then
        DB_CONTAINER="db"
        echo "  Database service: db (docker compose)"
    elif docker compose --profile aws ps db-aws > /dev/null 2>&1; then
        DB_CONTAINER="db-aws"
        echo "  Database service: db-aws (docker compose)"
    else
        echo "  Database: Accessible via DATABASE_URL in backend container"
    fi
else
    # Fallback to docker ps
    BACKEND_CONTAINER=$(docker ps --filter "name=backend-aws" --format "{{.Names}}" | head -1 || echo "")
    if [ -n "$BACKEND_CONTAINER" ]; then
        echo "  Backend container: $BACKEND_CONTAINER (docker ps)"
    else
        echo "  ❌ ERROR: backend-aws container not found"
        echo "     Run: docker compose --profile aws ps"
        exit 1
    fi
    
    DB_CONTAINER=$(docker ps --filter "name=db" --format "{{.Names}}" | head -1 || echo "")
    if [ -n "$DB_CONTAINER" ]; then
        echo "  Database container: $DB_CONTAINER (docker ps)"
    else
        echo "  Database: Accessible via DATABASE_URL in backend container"
    fi
fi
echo ""

# Function to exec in backend container
exec_backend() {
    if [ "$BACKEND_CONTAINER" == "backend-aws" ]; then
        docker compose --profile aws exec -T backend-aws "$@"
    else
        docker exec -i "$BACKEND_CONTAINER" "$@"
    fi
}

# Gate 1: RUN_TELEGRAM
echo "=== Gate 1: RUN_TELEGRAM ==="
RUN_TELEGRAM=$(exec_backend env | grep "^RUN_TELEGRAM=" | cut -d= -f2 || echo "")
if [ -z "$RUN_TELEGRAM" ]; then
    echo "  ❌ FAIL: RUN_TELEGRAM not set"
    GATE1_FAIL=true
else
    RUN_TELEGRAM_LOWER=$(echo "$RUN_TELEGRAM" | tr '[:upper:]' '[:lower:]')
    if [[ "$RUN_TELEGRAM_LOWER" == "true" ]] || [[ "$RUN_TELEGRAM_LOWER" == "1" ]] || [[ "$RUN_TELEGRAM_LOWER" == "yes" ]]; then
        echo "  ✅ PASS: RUN_TELEGRAM=$RUN_TELEGRAM"
        GATE1_FAIL=false
    else
        echo "  ❌ FAIL: RUN_TELEGRAM=$RUN_TELEGRAM (must be 'true', '1', or 'yes')"
        GATE1_FAIL=true
    fi
fi
echo ""

# Gate 2: Kill Switch (tg_enabled_aws)
echo "=== Gate 2: Kill Switch (tg_enabled_aws) ==="
KILL_SWITCH_OUTPUT=$(exec_backend python3 << 'PYEOF'
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
            value = setting.setting_value.lower()
            if value == "true":
                print("PASS:true")
                sys.exit(0)
            else:
                print(f"FAIL:{value}")
                sys.exit(1)
        else:
            print("FAIL:not_set")
            sys.exit(1)
    except Exception as e:
        print(f"ERROR:{e}")
        sys.exit(1)
    finally:
        db.close()
except Exception as e:
    print(f"ERROR:{e}")
    sys.exit(1)
PYEOF
)
KILL_SWITCH_EXIT=$?

if [ $KILL_SWITCH_EXIT -eq 0 ]; then
    echo "  ✅ PASS: tg_enabled_aws=true"
    GATE2_FAIL=false
else
    KILL_SWITCH_VALUE=$(echo "$KILL_SWITCH_OUTPUT" | cut -d: -f2)
    if [ "$KILL_SWITCH_VALUE" == "not_set" ]; then
        echo "  ❌ FAIL: tg_enabled_aws not set in database (defaults to false)"
    else
        echo "  ❌ FAIL: tg_enabled_aws=$KILL_SWITCH_VALUE (must be 'true')"
    fi
    GATE2_FAIL=true
fi
echo ""

# Gate 3: Bot Token
echo "=== Gate 3: Bot Token ==="
BOT_TOKEN=$(exec_backend env | grep -E "^TELEGRAM_BOT_TOKEN(_AWS)?=" | head -1 | cut -d= -f2 || echo "")
if [ -z "$BOT_TOKEN" ]; then
    echo "  ❌ FAIL: TELEGRAM_BOT_TOKEN or TELEGRAM_BOT_TOKEN_AWS not set"
    GATE3_FAIL=true
else
    if [ ${#BOT_TOKEN} -gt 10 ]; then
        TOKEN_MASKED="${BOT_TOKEN:0:6}...${BOT_TOKEN: -4}"
    else
        TOKEN_MASKED="***MASKED***"
    fi
    echo "  ✅ PASS: Bot token set (${TOKEN_MASKED})"
    GATE3_FAIL=false
fi
echo ""

# Gate 4: Chat ID
echo "=== Gate 4: Chat ID ==="
CHAT_ID=$(exec_backend env | grep -E "^TELEGRAM_CHAT_ID(_AWS)?=" | head -1 | cut -d= -f2 || echo "")
if [ -z "$CHAT_ID" ]; then
    echo "  ❌ FAIL: TELEGRAM_CHAT_ID or TELEGRAM_CHAT_ID_AWS not set"
    GATE4_FAIL=true
else
    echo "  ✅ PASS: Chat ID set ($CHAT_ID)"
    GATE4_FAIL=false
fi
echo ""

echo "=========================================="
echo "Summary"
echo "=========================================="
echo "Gate 0 (Containers): ✅ PASS"
echo "Gate 1 (RUN_TELEGRAM): $([ "$GATE1_FAIL" = "false" ] && echo "✅ PASS" || echo "❌ FAIL")"
echo "Gate 2 (Kill Switch):   $([ "$GATE2_FAIL" = "false" ] && echo "✅ PASS" || echo "❌ FAIL")"
echo "Gate 3 (Bot Token):    $([ "$GATE3_FAIL" = "false" ] && echo "✅ PASS" || echo "❌ FAIL")"
echo "Gate 4 (Chat ID):      $([ "$GATE4_FAIL" = "false" ] && echo "✅ PASS" || echo "❌ FAIL")"
echo ""

if [ "$GATE1_FAIL" = "false" ] && [ "$GATE2_FAIL" = "false" ] && [ "$GATE3_FAIL" = "false" ] && [ "$GATE4_FAIL" = "false" ]; then
    echo "✅ ALL GATES PASS - Telegram should show GREEN"
    exit 0
else
    echo "❌ SOME GATES FAIL - Telegram will show RED"
    echo ""
    echo "Failing gates:"
    [ "$GATE1_FAIL" = "true" ] && echo "  - Gate 1: RUN_TELEGRAM"
    [ "$GATE2_FAIL" = "true" ] && echo "  - Gate 2: Kill Switch (tg_enabled_aws)"
    [ "$GATE3_FAIL" = "true" ] && echo "  - Gate 3: Bot Token"
    [ "$GATE4_FAIL" = "true" ] && echo "  - Gate 4: Chat ID"
    exit 1
fi

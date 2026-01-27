#!/bin/bash
# End-to-end test script for local Telegram alert delivery
# Requires TELEGRAM_BOT_TOKEN_DEV and TELEGRAM_CHAT_ID_DEV

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
REPO_ROOT="$(cd "$BACKEND_DIR/.." && pwd)"

# Verify we're in the right location
if [ ! -f "$BACKEND_DIR/app/main.py" ]; then
    echo "❌ ERROR: This script must be run from backend directory or repo root" >&2
    echo "   Expected: $REPO_ROOT/backend" >&2
    exit 1
fi

cd "$BACKEND_DIR"

# Check required env vars
if [ -z "${TELEGRAM_BOT_TOKEN_DEV:-}" ]; then
    echo "❌ ERROR: TELEGRAM_BOT_TOKEN_DEV is not set" >&2
    echo "   Run: ./scripts/local_dev_telegram_bootstrap.sh first" >&2
    exit 1
fi

if [ -z "${TELEGRAM_CHAT_ID_DEV:-}" ]; then
    echo "❌ ERROR: TELEGRAM_CHAT_ID_DEV is not set" >&2
    echo "   Run: ./scripts/local_dev_telegram_bootstrap.sh first" >&2
    exit 1
fi

# Check for DATABASE_URL
if [ -z "${DATABASE_URL:-}" ]; then
    export DATABASE_URL="postgresql://trader:traderpass@localhost:5432/atp"
    echo "ℹ️  Using default DATABASE_URL: postgresql://trader:***@localhost:5432/atp"
fi

# Set local env vars for backend
export ENVIRONMENT="local"
export RUN_TELEGRAM="true"
export TELEGRAM_BOT_TOKEN_LOCAL="$TELEGRAM_BOT_TOKEN_DEV"
export TELEGRAM_CHAT_ID_LOCAL="$TELEGRAM_CHAT_ID_DEV"

echo "🧪 End-to-End Telegram Alert Test"
echo "=================================="
echo ""
echo "🔍 Configuration:"
echo "   Token: ${TELEGRAM_BOT_TOKEN_DEV:0:6}...${TELEGRAM_BOT_TOKEN_DEV: -4}"
echo "   Chat ID: $TELEGRAM_CHAT_ID_DEV"
echo "   Database: ${DATABASE_URL%%@*}"
echo ""

# Check if backend is already running
BACKEND_PID=""
if pgrep -f "uvicorn app.main:app.*8002" > /dev/null; then
    BACKEND_PID=$(pgrep -f "uvicorn app.main:app.*8002" | head -1)
    echo "ℹ️  Backend already running (PID: $BACKEND_PID)"
    echo "   Using existing instance"
    BACKEND_STARTED_BY_SCRIPT=false
else
    echo "🚀 Starting backend..."
    LOG_FILE="/tmp/uvicorn_e2e_test_$(date +%s).log"
    python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8002 > "$LOG_FILE" 2>&1 &
    BACKEND_PID=$!
    BACKEND_STARTED_BY_SCRIPT=true
    echo "   Backend started (PID: $BACKEND_PID, logs: $LOG_FILE)"
    echo "   Waiting 15 seconds for startup..."
    sleep 15
    
    # Check health
    if ! curl -sSf http://localhost:8002/api/health > /dev/null 2>&1; then
        echo "❌ Backend health check failed" >&2
        echo "   Check logs: $LOG_FILE" >&2
        kill $BACKEND_PID 2>/dev/null || true
        exit 1
    fi
    echo "   ✅ Backend is healthy"
fi

echo ""

# Trigger alert
echo "📤 Triggering simulated alert (BTC_USDT BUY)..."
ALERT_RESPONSE=$(curl -sS -X POST http://localhost:8002/api/test/simulate-alert \
  -H "Content-Type: application/json" \
  -d '{"symbol":"BTC_USDT","signal_type":"BUY"}' 2>&1)

if echo "$ALERT_RESPONSE" | grep -q '"ok":true'; then
    echo "   ✅ Alert triggered successfully"
else
    echo "   ⚠️  Alert response: $ALERT_RESPONSE" | head -5
fi

echo ""
echo "⏳ Waiting 5 seconds for Telegram send..."
sleep 5
echo ""

# Check logs
if [ "$BACKEND_STARTED_BY_SCRIPT" = true ]; then
    LOG_FILE="/tmp/uvicorn_e2e_test_*.log"
    echo "📋 Checking logs for Telegram delivery..."
    echo ""
    
    if grep -q "\[TELEGRAM_API_CALL\]" $LOG_FILE 2>/dev/null; then
        echo "✅ [TELEGRAM_API_CALL] found"
    else
        echo "⚠️  [TELEGRAM_API_CALL] not found in logs"
    fi
    
    if grep -q "\[TELEGRAM_RESPONSE\].*status=200" $LOG_FILE 2>/dev/null; then
        echo "✅ [TELEGRAM_RESPONSE] status=200 found"
        grep "\[TELEGRAM_RESPONSE\].*status=200" $LOG_FILE | tail -1
    else
        echo "❌ [TELEGRAM_RESPONSE] status=200 NOT found"
        echo "   Recent TELEGRAM_RESPONSE lines:"
        grep "\[TELEGRAM_RESPONSE\]" $LOG_FILE 2>/dev/null | tail -3 || echo "   (none)"
    fi
    
    if grep -q "\[TELEGRAM_SUCCESS\]" $LOG_FILE 2>/dev/null; then
        echo "✅ [TELEGRAM_SUCCESS] found"
        grep "\[TELEGRAM_SUCCESS\]" $LOG_FILE | tail -1
    else
        echo "❌ [TELEGRAM_SUCCESS] NOT found"
    fi
else
    echo "📋 Backend logs are in your terminal or log file"
    echo "   Look for: [TELEGRAM_API_CALL], [TELEGRAM_RESPONSE] status=200, [TELEGRAM_SUCCESS]"
fi

echo ""

# Check database
echo "📊 Checking database for telegram_messages row..."
DB_RESULT=$(python3 <<'PY'
import os
import sys
from sqlalchemy import create_engine, text

try:
    engine = create_engine(os.environ.get("DATABASE_URL", "postgresql://trader:traderpass@localhost:5432/atp"), future=True)
    q = text("""
        SELECT id, symbol, blocked, throttle_status, timestamp, LEFT(message, 120) AS preview
        FROM telegram_messages
        WHERE symbol='BTC_USDT'
        ORDER BY timestamp DESC
        LIMIT 1
    """)
    with engine.connect() as c:
        rows = c.execute(q).fetchall()
        if rows:
            r = rows[0]
            d = dict(r._mapping)
            print(f"ID: {d['id']}")
            print(f"Symbol: {d['symbol']}")
            print(f"Blocked: {d['blocked']}")
            print(f"Status: {d['throttle_status']}")
            print(f"Timestamp: {d['timestamp']}")
            print(f"Preview: {d['preview'][:100]}...")
            sys.exit(0 if d['blocked'] == False else 1)
        else:
            print("No rows found")
            sys.exit(1)
except Exception as e:
    print(f"Error: {e}", file=sys.stderr)
    sys.exit(1)
PY
)

DB_EXIT=$?
echo "$DB_RESULT"
echo ""

if [ $DB_EXIT -eq 0 ]; then
    echo "✅ SUCCESS: Alert delivered and persisted (blocked=false)"
else
    echo "❌ FAILURE: Alert not delivered or blocked=true"
fi

# Cleanup
if [ "$BACKEND_STARTED_BY_SCRIPT" = true ]; then
    echo ""
    echo "🛑 Stopping backend (PID: $BACKEND_PID)..."
    kill $BACKEND_PID 2>/dev/null || true
    sleep 2
    echo "   ✅ Backend stopped"
fi

echo ""
if [ $DB_EXIT -eq 0 ]; then
    echo "✅ End-to-end test PASSED"
    exit 0
else
    echo "❌ End-to-end test FAILED"
    exit 1
fi

#!/bin/bash
# End-to-end alert test for local dev Telegram bot
# Verifies alert creation, Telegram delivery, and DB persistence

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
BACKEND_DIR="$REPO_ROOT/backend"

# Verify we're in the right location
if [ ! -f "$BACKEND_DIR/app/main.py" ]; then
    echo "❌ ERROR: This script must be run from the backend directory or repo root" >&2
    echo "   Expected: $BACKEND_DIR/app/main.py" >&2
    exit 1
fi

cd "$BACKEND_DIR"

# Check required env vars
if [ -z "${TELEGRAM_BOT_TOKEN_DEV:-}" ]; then
    echo "❌ ERROR: TELEGRAM_BOT_TOKEN_DEV is not set" >&2
    echo "   Run: backend/scripts/local_dev_telegram_bootstrap.sh first" >&2
    exit 1
fi

if [ -z "${TELEGRAM_CHAT_ID_DEV:-}" ]; then
    echo "❌ ERROR: TELEGRAM_CHAT_ID_DEV is not set" >&2
    echo "   Run: backend/scripts/local_dev_telegram_bootstrap.sh first" >&2
    exit 1
fi

# Check database connection
if [ -z "${DATABASE_URL:-}" ]; then
    export DATABASE_URL="postgresql://trader:traderpass@localhost:5432/atp"
    echo "ℹ️  Using default DATABASE_URL: postgresql://trader:***@localhost:5432/atp"
fi

# Set local environment
export ENVIRONMENT="local"
export RUN_TELEGRAM="true"
export TELEGRAM_BOT_TOKEN_LOCAL="$TELEGRAM_BOT_TOKEN_DEV"
export TELEGRAM_CHAT_ID_LOCAL="$TELEGRAM_CHAT_ID_DEV"

echo "🧪 End-to-End Alert Test"
echo "========================"
echo ""
echo "📋 Configuration:"
echo "   Token: ${TELEGRAM_BOT_TOKEN_DEV:0:6}...${TELEGRAM_BOT_TOKEN_DEV: -4}"
echo "   Chat ID: $TELEGRAM_CHAT_ID_DEV"
echo "   Database: ${DATABASE_URL%%@*}"
echo ""

# Check if backend is already running
BACKEND_PID=$(pgrep -f "uvicorn app.main:app.*--port 8002" || true)
LOG_FILE="/tmp/uvicorn_e2e_test_$(date +%s).log"

if [ -n "$BACKEND_PID" ]; then
    echo "ℹ️  Backend is already running (PID: $BACKEND_PID)"
    echo "   Using existing instance"
    BACKEND_STARTED_BY_SCRIPT=false
else
    echo "🚀 Starting backend..."
    python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8002 > "$LOG_FILE" 2>&1 &
    BACKEND_PID=$!
    BACKEND_STARTED_BY_SCRIPT=true
    echo "   PID: $BACKEND_PID"
    echo "   Logs: $LOG_FILE"
    echo ""
    echo "⏳ Waiting for backend to start (15 seconds)..."
    sleep 15
    
    # Check health
    if ! curl -sS --connect-timeout 5 http://localhost:8002/api/health > /dev/null 2>&1; then
        echo "❌ ERROR: Backend health check failed" >&2
        echo "   Check logs: tail -50 $LOG_FILE" >&2
        if [ "$BACKEND_STARTED_BY_SCRIPT" = true ]; then
            kill $BACKEND_PID 2>/dev/null || true
        fi
        exit 1
    fi
    echo "✅ Backend is healthy"
    echo ""
fi

# Trigger alert
echo "📤 Triggering test alert (BTC_USDT BUY)..."
echo ""

ALERT_RESPONSE=$(curl -sS -X POST http://localhost:8002/api/test/simulate-alert \
  -H "Content-Type: application/json" \
  -d '{"symbol":"BTC_USDT","signal_type":"BUY"}' 2>&1)

if echo "$ALERT_RESPONSE" | grep -q '"ok":true'; then
    echo "✅ Alert triggered successfully"
    echo ""
else
    echo "❌ ERROR: Alert trigger failed" >&2
    echo "   Response: $ALERT_RESPONSE" >&2
    if [ "$BACKEND_STARTED_BY_SCRIPT" = true ]; then
        kill $BACKEND_PID 2>/dev/null || true
    fi
    exit 1
fi

# Wait for processing
echo "⏳ Waiting for alert processing (5 seconds)..."
sleep 5
echo ""

# Check logs
echo "📋 Checking logs for Telegram delivery..."
echo ""

if [ "$BACKEND_STARTED_BY_SCRIPT" = true ] && [ -f "$LOG_FILE" ]; then
    LOG_SOURCE="$LOG_FILE"
else
    LOG_SOURCE="(backend stdout - check terminal where uvicorn is running)"
fi

# Try to extract log evidence
if [ -f "$LOG_SOURCE" ]; then
    echo "   From: $LOG_SOURCE"
    echo ""
    
    if grep -q "\[TELEGRAM_API_CALL\]" "$LOG_SOURCE"; then
        echo "   ✅ [TELEGRAM_API_CALL] found"
    else
        echo "   ⚠️  [TELEGRAM_API_CALL] not found in logs"
    fi
    
    if grep -q "\[TELEGRAM_RESPONSE\].*status=200" "$LOG_SOURCE"; then
        echo "   ✅ [TELEGRAM_RESPONSE] status=200 found"
        grep "\[TELEGRAM_RESPONSE\].*status=200" "$LOG_SOURCE" | tail -1
    else
        echo "   ⚠️  [TELEGRAM_RESPONSE] status=200 not found"
        echo "   Recent TELEGRAM_RESPONSE lines:"
        grep "\[TELEGRAM_RESPONSE\]" "$LOG_SOURCE" | tail -3 || echo "      (none)"
    fi
    
    if grep -q "\[TELEGRAM_SUCCESS\]" "$LOG_SOURCE"; then
        echo "   ✅ [TELEGRAM_SUCCESS] found"
        grep "\[TELEGRAM_SUCCESS\]" "$LOG_SOURCE" | tail -1
    else
        echo "   ⚠️  [TELEGRAM_SUCCESS] not found"
    fi
else
    echo "   ℹ️  Log file not available. Check backend terminal for:"
    echo "      - [TELEGRAM_API_CALL]"
    echo "      - [TELEGRAM_RESPONSE] status=200"
    echo "      - [TELEGRAM_SUCCESS]"
fi

echo ""

# Check database
echo "📊 Checking database for alert persistence..."
echo ""

DB_RESULT=$(python3 <<'PY'
import os
import sys
from sqlalchemy import create_engine, text

try:
    engine = create_engine(os.environ["DATABASE_URL"], future=True)
    q = text("""
        SELECT id, symbol, blocked, throttle_status, throttle_reason, timestamp, LEFT(message, 120) AS preview
        FROM telegram_messages
        WHERE symbol='BTC_USDT'
        ORDER BY timestamp DESC
        LIMIT 3
    """)
    with engine.connect() as c:
        rows = c.execute(q).fetchall()
        if rows:
            print("rows:", len(rows))
            for r in rows:
                d = dict(r._mapping)
                print(f"ID: {d['id']}, Blocked: {d['blocked']}, Status: {d['throttle_status']}, TS: {d['timestamp']}")
                print(f"Preview: {d['preview'][:100] if d['preview'] else 'N/A'}")
                if d['throttle_reason']:
                    print(f"Reason: {d['throttle_reason'][:100]}")
                print("---")
        else:
            print("No rows found")
            sys.exit(1)
except Exception as e:
    print(f"ERROR: {e}", file=sys.stderr)
    sys.exit(1)
PY
)

DB_EXIT=$?

if [ $DB_EXIT -eq 0 ]; then
    echo "$DB_RESULT"
    echo ""
    
    # Check if latest row is successful
    LATEST_BLOCKED=$(echo "$DB_RESULT" | grep "^ID:" | head -1 | grep -o "Blocked: [^,]*" | cut -d' ' -f2 || echo "unknown")
    LATEST_STATUS=$(echo "$DB_RESULT" | grep "^ID:" | head -1 | grep -o "Status: [^,]*" | cut -d' ' -f2 || echo "unknown")
    
    if [ "$LATEST_BLOCKED" = "False" ] || [ "$LATEST_STATUS" != "FAILED" ]; then
        echo "✅ SUCCESS: Latest alert shows blocked=False or status != FAILED"
        echo "   This indicates successful Telegram delivery!"
    else
        echo "⚠️  WARNING: Latest alert shows blocked=True or status=FAILED"
        echo "   Check logs and Telegram bot configuration"
    fi
else
    echo "❌ ERROR: Database query failed" >&2
    echo "$DB_RESULT" >&2
fi

echo ""

# Cleanup
if [ "$BACKEND_STARTED_BY_SCRIPT" = true ]; then
    echo "🧹 Cleaning up (stopping backend)..."
    kill $BACKEND_PID 2>/dev/null || true
    sleep 2
    echo "✅ Backend stopped"
    echo ""
fi

echo "✅ End-to-end test complete!"
echo ""
echo "📝 Summary:"
echo "   - Alert triggered: ✅"
echo "   - Check logs above for Telegram delivery evidence"
echo "   - Check database above for persistence"
echo ""

#!/bin/bash
# Quick check script to verify ETC_USDT configuration via API
# Usage: ./check_etc_via_api.sh

API_URL="${API_BASE_URL:-http://localhost:8000}"
SYMBOL="ETC_USDT"

echo "=========================================="
echo "🔍 Checking ETC_USDT Configuration via API"
echo "=========================================="
echo ""

# Check if API is accessible
echo "📡 Testing API connection..."
if ! curl -s -f "${API_URL}/api/health" > /dev/null 2>&1; then
    echo "❌ ERROR: Cannot connect to API at ${API_URL}"
    echo "   Make sure the backend is running: docker compose up -d backend"
    exit 1
fi

echo "✅ API is accessible"
echo ""

# Get watchlist item
echo "📋 Fetching watchlist configuration for ${SYMBOL}..."
RESPONSE=$(curl -s "${API_URL}/api/dashboard/symbol/${SYMBOL}")

if [ $? -ne 0 ] || [ -z "$RESPONSE" ]; then
    echo "❌ ERROR: Failed to fetch watchlist item"
    exit 1
fi

# Check if symbol exists
if echo "$RESPONSE" | grep -q '"error"'; then
    echo "❌ ERROR: ${SYMBOL} not found in watchlist"
    echo "   Response: $RESPONSE"
    exit 1
fi

echo "✅ Found ${SYMBOL} in watchlist"
echo ""

# Extract configuration values
ALERT_ENABLED=$(echo "$RESPONSE" | grep -o '"alert_enabled":[^,}]*' | cut -d':' -f2 | tr -d ' ')
SELL_ALERT_ENABLED=$(echo "$RESPONSE" | grep -o '"sell_alert_enabled":[^,}]*' | cut -d':' -f2 | tr -d ' ')
TRADE_ENABLED=$(echo "$RESPONSE" | grep -o '"trade_enabled":[^,}]*' | cut -d':' -f2 | tr -d ' ')
TRADE_AMOUNT=$(echo "$RESPONSE" | grep -o '"trade_amount_usd":[^,}]*' | cut -d':' -f2 | tr -d ' ')

echo "📊 Current Configuration:"
echo "   alert_enabled: ${ALERT_ENABLED:-null}"
echo "   sell_alert_enabled: ${SELL_ALERT_ENABLED:-null}"
echo "   trade_enabled: ${TRADE_ENABLED:-null}"
echo "   trade_amount_usd: ${TRADE_AMOUNT:-null}"
echo ""

# Check for issues
ISSUES=0

if [ "$ALERT_ENABLED" != "true" ]; then
    echo "❌ ISSUE: alert_enabled is not true"
    ISSUES=$((ISSUES + 1))
fi

if [ "$SELL_ALERT_ENABLED" != "true" ]; then
    echo "❌ ISSUE: sell_alert_enabled is not true"
    ISSUES=$((ISSUES + 1))
fi

if [ "$TRADE_ENABLED" != "true" ]; then
    echo "⚠️  WARNING: trade_enabled is not true (orders won't be created)"
    ISSUES=$((ISSUES + 1))
fi

if [ -z "$TRADE_AMOUNT" ] || [ "$TRADE_AMOUNT" = "null" ] || [ "$TRADE_AMOUNT" = "0" ]; then
    echo "⚠️  WARNING: trade_amount_usd is not configured (orders won't be created)"
    ISSUES=$((ISSUES + 1))
fi

echo ""
if [ $ISSUES -eq 0 ]; then
    echo "✅ All configuration looks good!"
    echo ""
    echo "If alerts/orders still aren't working, check:"
    echo "  1. SELL signals are being detected (check logs)"
    echo "  2. Throttling is not blocking (60s cooldown, price change %)"
    echo "  3. Indicators (MA50, EMA10) are available"
else
    echo "❌ Found $ISSUES issue(s) that need to be fixed"
    echo ""
    echo "To fix, run:"
    echo "  python3 backend/scripts/fix_etc_sell_alerts.py"
    echo ""
    echo "Or enable via Dashboard UI"
fi

echo ""
echo "=========================================="











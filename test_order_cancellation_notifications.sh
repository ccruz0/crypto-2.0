#!/bin/bash

# Test script for Order Cancellation Notifications
# This script helps verify that Telegram notifications are sent when orders are cancelled

set -e

# Configuration
API_BASE_URL="${API_BASE_URL:-http://localhost:8002}"
API_TOKEN="${API_TOKEN:-}"

# Colors for output
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo "🧪 Testing Order Cancellation Notifications"
echo "=========================================="
echo ""

# Step 1: Get open orders
echo "📋 Step 1: Fetching open orders..."
echo ""

if [ -z "$API_TOKEN" ]; then
    echo -e "${YELLOW}⚠️  Warning: API_TOKEN not set. Using unauthenticated request.${NC}"
    ORDERS_RESPONSE=$(curl -s -X GET "${API_BASE_URL}/api/orders/open" \
        -H "Content-Type: application/json" 2>&1)
else
    ORDERS_RESPONSE=$(curl -s -X GET "${API_BASE_URL}/api/orders/open" \
        -H "Content-Type: application/json" \
        -H "Authorization: Bearer ${API_TOKEN}" 2>&1)
fi

if [ $? -ne 0 ]; then
    echo -e "${RED}❌ Failed to fetch open orders${NC}"
    echo "Response: $ORDERS_RESPONSE"
    exit 1
fi

# Check if we got valid JSON
if ! echo "$ORDERS_RESPONSE" | jq . > /dev/null 2>&1; then
    echo -e "${RED}❌ Invalid JSON response${NC}"
    echo "Response: $ORDERS_RESPONSE"
    exit 1
fi

# Extract orders
ORDERS_COUNT=$(echo "$ORDERS_RESPONSE" | jq '.orders | length' 2>/dev/null || echo "0")

if [ "$ORDERS_COUNT" = "0" ] || [ -z "$ORDERS_COUNT" ]; then
    echo -e "${YELLOW}⚠️  No open orders found. Cannot test cancellation.${NC}"
    echo ""
    echo "To test, you need to:"
    echo "  1. Place a test order first"
    echo "  2. Or use an existing order ID"
    echo ""
    read -p "Do you have an order ID to test with? (y/n): " HAS_ORDER_ID
    if [ "$HAS_ORDER_ID" != "y" ]; then
        echo "Exiting. Please place an order first or provide an order ID."
        exit 0
    fi
    read -p "Enter order ID to cancel: " ORDER_ID
else
    echo -e "${GREEN}✅ Found $ORDERS_COUNT open order(s)${NC}"
    echo ""
    echo "Open orders:"
    echo "$ORDERS_RESPONSE" | jq -r '.orders[] | "  - \(.exchange_order_id) | \(.symbol) | \(.side) | \(.order_type) | Status: \(.status)"' 2>/dev/null || echo "$ORDERS_RESPONSE"
    echo ""
    read -p "Enter order ID to cancel (or press Enter to use first order): " ORDER_ID
    
    if [ -z "$ORDER_ID" ]; then
        ORDER_ID=$(echo "$ORDERS_RESPONSE" | jq -r '.orders[0].exchange_order_id' 2>/dev/null)
        echo -e "${YELLOW}Using first order: $ORDER_ID${NC}"
    fi
fi

if [ -z "$ORDER_ID" ]; then
    echo -e "${RED}❌ No order ID provided${NC}"
    exit 1
fi

echo ""
echo "📤 Step 2: Cancelling order $ORDER_ID..."
echo ""

# Cancel the order
if [ -z "$API_TOKEN" ]; then
    CANCEL_RESPONSE=$(curl -s -X POST "${API_BASE_URL}/api/orders/cancel" \
        -H "Content-Type: application/json" \
        -d "{\"exchange\": \"CRYPTO_COM\", \"order_id\": \"$ORDER_ID\"}" 2>&1)
else
    CANCEL_RESPONSE=$(curl -s -X POST "${API_BASE_URL}/api/orders/cancel" \
        -H "Content-Type: application/json" \
        -H "Authorization: Bearer ${API_TOKEN}" \
        -d "{\"exchange\": \"CRYPTO_COM\", \"order_id\": \"$ORDER_ID\"}" 2>&1)
fi

if [ $? -ne 0 ]; then
    echo -e "${RED}❌ Failed to cancel order${NC}"
    echo "Response: $CANCEL_RESPONSE"
    exit 1
fi

# Check response
if echo "$CANCEL_RESPONSE" | jq . > /dev/null 2>&1; then
    OK=$(echo "$CANCEL_RESPONSE" | jq -r '.ok' 2>/dev/null)
    if [ "$OK" = "true" ]; then
        echo -e "${GREEN}✅ Order cancelled successfully!${NC}"
        echo ""
        echo "Response:"
        echo "$CANCEL_RESPONSE" | jq . 2>/dev/null || echo "$CANCEL_RESPONSE"
    else
        echo -e "${RED}❌ Order cancellation failed${NC}"
        echo "Response: $CANCEL_RESPONSE"
        exit 1
    fi
else
    echo -e "${YELLOW}⚠️  Unexpected response format${NC}"
    echo "Response: $CANCEL_RESPONSE"
fi

echo ""
echo "📱 Step 3: Check Telegram channel"
echo ""
echo -e "${YELLOW}Please check your Telegram channel for the cancellation notification.${NC}"
echo ""
echo "Expected notification format:"
echo "  ❌ ORDER CANCELLED"
echo "  📊 Symbol: [SYMBOL]"
echo "  🔄 Side: [BUY/SELL]"
echo "  🎯 Type: [ORDER_TYPE]"
echo "  📋 Order ID: [ORDER_ID]"
echo "  💡 Reason: Manual cancellation via API"
echo ""
read -p "Did you receive the Telegram notification? (y/n): " NOTIFICATION_RECEIVED

if [ "$NOTIFICATION_RECEIVED" = "y" ]; then
    echo -e "${GREEN}✅ SUCCESS! Notification received!${NC}"
    echo ""
    echo "✅ Test passed: Order cancellation notification is working!"
else
    echo -e "${RED}❌ Notification not received${NC}"
    echo ""
    echo "Troubleshooting steps:"
    echo "  1. Check backend logs: docker compose --profile aws logs backend-aws | grep -i notification"
    echo "  2. Verify Telegram configuration (TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID)"
    echo "  3. Check if bot is added to Telegram channel"
    echo "  4. Verify backend service is running on AWS"
    echo ""
    echo "See docs/ORDER_CANCELLATION_NOTIFICATIONS.md for troubleshooting guide"
fi

echo ""
echo "📊 Step 4: Check logs (optional)"
echo ""
read -p "Check backend logs for notification activity? (y/n): " CHECK_LOGS

if [ "$CHECK_LOGS" = "y" ]; then
    echo ""
    echo "Checking logs on AWS instance..."
    ssh hilovivo-aws 'cd ~/automated-trading-platform && docker compose --profile aws logs backend-aws --tail 100 | grep -i "notification\|cancel.*order.*'$ORDER_ID'" | tail -20' 2>&1 || echo "Could not check logs remotely"
fi

echo ""
echo "✅ Test complete!"




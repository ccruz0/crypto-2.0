#!/bin/bash
# Script to create SL/TP orders for the last SOL_USDT order via API

API_URL="${API_URL:-http://localhost:8000}"
SYMBOL="${1:-SOL_USDT}"

echo "Creating SL/TP orders for last ${SYMBOL} order..."
echo "API URL: ${API_URL}"

response=$(curl -s -X POST "${API_URL}/api/orders/create-sl-tp-for-last-order?symbol=${SYMBOL}")

if [ $? -eq 0 ]; then
    echo "Response:"
    echo "$response" | python3 -m json.tool 2>/dev/null || echo "$response"
else
    echo "Error: Failed to connect to API at ${API_URL}"
    echo "Make sure the backend is running and accessible."
    exit 1
fi


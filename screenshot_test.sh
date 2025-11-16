#!/bin/bash
echo "===================================================================================================="
echo "CRYPTO.COM EXCHANGE API v1 - AUTHENTICATION TEST"
echo "===================================================================================================="
echo ""
echo "Date: $(date)"
echo ""
echo "Testing API endpoint: https://api.crypto.com/exchange/v1/private/get-account-summary"
echo ""
echo "Making request..."
echo ""

curl -X POST "https://api.crypto.com/exchange/v1/private/get-account-summary" \
  -H "Content-Type: application/json" \
  -d '{
    "id": '$(date +%s)'000,
    "method": "private/get-account-summary",
    "api_key": "z3HWF8m292zJKABkzfXWvQ",
    "sig": "test_signature",
    "nonce": '$(date +%s)'000,
    "params": {}
  }'

echo ""
echo ""
echo "===================================================================================================="
echo "If you see error 40101, this confirms the authentication issue"
echo "===================================================================================================="


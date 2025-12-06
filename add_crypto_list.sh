#!/bin/bash

# Script to add the 20 main cryptocurrencies to the watchlist
API_URL="http://54.254.150.31:8000/api"
API_KEY="demo-key"

# List of cryptocurrencies to add
declare -a symbols=(
    "BTC_USD"
    "ETH_USD"
    "USDT_USD"
    "USDC_USD"
    "BNB_USD"
    "ADA_USD"
    "SOL_USD"
    "XRP_USD"
    "DOGE_USD"
    "DOT_USD"
    "AVAX_USD"
    "LTC_USD"
    "LINK_USD"
    "UNI_USD"
    "XLM_USD"
    "BCH_USD"
    "SUI_USD"
    "VET_USD"
    "CRO_USD"
    "HBAR_USD"
)

echo "Adding cryptocurrencies to watchlist..."

for symbol in "${symbols[@]}"; do
    echo "Adding $symbol..."
    
    # Add symbol to watchlist
    response=$(curl -s -X POST -H "X-API-Key: $API_KEY" -H "Content-Type: application/json" \
        -d "{\"symbol\":\"$symbol\",\"exchange\":\"CRYPTO_COM\",\"trade_enabled\":true,\"trade_amount_usd\":50,\"trade_on_margin\":false,\"sl_tp_mode\":\"conservative\",\"sl_percentage\":5.0,\"tp_percentage\":10.0}" \
        "$API_URL/dashboard")
    
    if echo "$response" | jq -e '.id' > /dev/null 2>&1; then
        echo "  ✅ $symbol added successfully"
    else
        echo "  ❌ Failed to add $symbol: $response"
    fi
    
    # Small delay to avoid rate limiting
    sleep 0.5
done

echo "Done! Check the dashboard to see all cryptocurrencies."







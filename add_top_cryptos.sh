#!/bin/bash

# Script to add top 20 cryptocurrencies to the watchlist
API_URL="http://54.254.150.31:8000/api"
API_KEY="demo-key"

# Top 20 cryptocurrencies with their USD pairs
declare -a symbols=(
    "BTC_USD"
    "ETH_USD" 
    "USDT_USD"
    "BNB_USD"
    "XRP_USD"
    "SOL_USD"
    "USDC_USD"
    "TRX_USD"
    "DOGE_USD"
    "ADA_USD"
    "LINK_USD"
    "XLM_USD"
    "BCH_USD"
    "SUI_USD"
    "LEO_USD"
    "AVAX_USD"
    "LTC_USD"
    "MATIC_USD"
    "DOT_USD"
    "UNI_USD"
)

echo "Adding top 20 cryptocurrencies to watchlist..."

for symbol in "${symbols[@]}"; do
    echo "Adding $symbol..."
    
    # Check if symbol already exists
    existing=$(curl -s -H "X-API-Key: $API_KEY" "$API_URL/dashboard" | jq -r ".[] | select(.symbol == \"$symbol\") | .symbol")
    
    if [ "$existing" = "$symbol" ]; then
        echo "  $symbol already exists, skipping..."
    else
        # Add symbol to watchlist
        response=$(curl -s -X POST -H "X-API-Key: $API_KEY" -H "Content-Type: application/json" \
            -d "{\"symbol\":\"$symbol\",\"exchange\":\"CRYPTO_COM\",\"trade_enabled\":true,\"trade_amount_usd\":50,\"trade_on_margin\":false,\"sl_tp_mode\":\"conservative\",\"sl_percentage\":5.0,\"tp_percentage\":10.0}" \
            "$API_URL/dashboard")
        
        if echo "$response" | jq -e '.id' > /dev/null 2>&1; then
            echo "  ✅ $symbol added successfully"
        else
            echo "  ❌ Failed to add $symbol: $response"
        fi
    fi
    
    # Small delay to avoid rate limiting
    sleep 0.5
done

echo "Done! Check the dashboard to see all cryptocurrencies."







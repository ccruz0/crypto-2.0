#!/bin/bash
# Simple script to trigger a manual alert and monitor decision tracing

SYMBOL=${1:-"ALGO_USDT"}
SIDE=${2:-"BUY"}

echo "🚀 Triggering manual alert for $SYMBOL $SIDE"
echo ""

cd "$(dirname "$0")/.."
. ./scripts/ssh_key.sh

# Get strategy key (assuming scalp:conservative for now, can be improved)
STRATEGY_KEY="scalp:conservative"

echo "1️⃣ Setting force_next_signal=True..."
ssh_cmd ubuntu@47.130.143.159 "cd ~/automated-trading-platform && docker compose --profile aws exec -T -e PGPASSWORD=traderpass db psql -U trader -d atp -c \"
UPDATE signal_throttle_states 
SET force_next_signal = TRUE 
WHERE symbol = '$SYMBOL' 
    AND side = '$SIDE' 
    AND strategy_key = '$STRATEGY_KEY';

SELECT symbol, side, strategy_key, force_next_signal, last_time 
FROM signal_throttle_states 
WHERE symbol = '$SYMBOL' AND side = '$SIDE';
\" 2>&1 | grep -v 'level=warning' | grep -v 'ADMIN_ACTIONS_KEY' | grep -v 'DIAGNOSTICS_API_KEY'"

echo ""
echo "2️⃣ Waiting 30 seconds for next monitoring cycle..."
sleep 30

echo ""
echo "3️⃣ Checking for new alerts and decision tracing..."
ssh_cmd ubuntu@47.130.143.159 "cd ~/automated-trading-platform && docker compose --profile aws exec -T -e PGPASSWORD=traderpass db psql -U trader -d atp -c \"
SELECT 
    id,
    symbol,
    LEFT(message, 80) as msg_preview,
    blocked,
    order_skipped,
    decision_type,
    reason_code,
    LEFT(reason_message, 60) as reason_preview,
    timestamp
FROM telegram_messages
WHERE symbol = '$SYMBOL'
    AND timestamp >= NOW() - INTERVAL '2 minutes'
    AND (
        message LIKE '%BUY SIGNAL%' 
        OR message LIKE '%SELL SIGNAL%'
        OR message LIKE '%TRADE BLOCKED%'
        OR message LIKE '%ORDER BLOCKED%'
    )
ORDER BY timestamp DESC
LIMIT 10;
\" 2>&1 | grep -v 'level=warning' | grep -v 'ADMIN_ACTIONS_KEY' | grep -v 'DIAGNOSTICS_API_KEY'"

echo ""
echo "4️⃣ Checking if order was created..."
ssh_cmd ubuntu@47.130.143.159 "cd ~/automated-trading-platform && docker compose --profile aws exec -T -e PGPASSWORD=traderpass db psql -U trader -d atp -c \"
SELECT 
    exchange_order_id,
    symbol,
    side,
    status,
    price,
    quantity,
    created_at
FROM exchange_orders
WHERE symbol = '$SYMBOL'
    AND created_at >= NOW() - INTERVAL '2 minutes'
    AND side = '$SIDE'
ORDER BY created_at DESC
LIMIT 1;
\" 2>&1 | grep -v 'level=warning' | grep -v 'ADMIN_ACTIONS_KEY' | grep -v 'DIAGNOSTICS_API_KEY'"

echo ""
echo "✅ Done! Check the output above for decision tracing information."


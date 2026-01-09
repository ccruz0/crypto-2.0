#!/bin/bash
# Monitor alerts and detect why orders are not executed

echo "🔍 Starting alert monitoring..."
echo "Monitoring alerts in real-time..."
echo "Press Ctrl+C to stop"
echo ""

while true; do
    echo ""
    echo "=== $(date '+%Y-%m-%d %H:%M:%S') ==="
    
    # Get recent alerts (last 2 minutes)
    ALERTS=$(docker compose --profile aws exec -T -e PGPASSWORD=traderpass db psql -U trader -d atp -c "
        SELECT 
            id,
            symbol,
            LEFT(message, 100) as msg_preview,
            blocked,
            order_skipped,
            decision_type,
            reason_code,
            LEFT(reason_message, 80) as reason_preview,
            timestamp
        FROM telegram_messages
        WHERE timestamp >= NOW() - INTERVAL '2 minutes'
            AND (message LIKE '%BUY SIGNAL%' OR message LIKE '%SELL SIGNAL%')
        ORDER BY timestamp DESC
        LIMIT 10;
    " 2>&1 | grep -v 'level=warning' | grep -v 'ADMIN_ACTIONS_KEY' | grep -v 'DIAGNOSTICS_API_KEY')
    
    if [ -n "$ALERTS" ] && [ "$ALERTS" != " id | symbol | msg_preview | blocked | order_skipped | decision_type | reason_code | reason_preview | timestamp " ] && [ "$ALERTS" != "----+--------+-------------+---------+---------------+---------------+-------------+----------------+-----------" ]; then
        echo "🚨 NEW ALERTS DETECTED:"
        echo "$ALERTS"
        
        # For each alert, check if order was created
        ALERT_IDS=$(echo "$ALERTS" | grep -E '^[[:space:]]*[0-9]+' | awk '{print $1}')
        
        for ALERT_ID in $ALERT_IDS; do
            if [ -n "$ALERT_ID" ] && [ "$ALERT_ID" != "id" ]; then
                # Get alert details
                ALERT_DETAILS=$(docker compose --profile aws exec -T -e PGPASSWORD=traderpass db psql -U trader -d atp -c "
                    SELECT 
                        tm.id,
                        tm.symbol,
                        tm.message,
                        tm.blocked,
                        tm.order_skipped,
                        tm.decision_type,
                        tm.reason_code,
                        tm.reason_message,
                        tm.context_json,
                        tm.timestamp as alert_time
                    FROM telegram_messages tm
                    WHERE tm.id = $ALERT_ID;
                " 2>&1 | grep -v 'level=warning' | grep -v 'ADMIN_ACTIONS_KEY' | grep -v 'DIAGNOSTICS_API_KEY')
                
                SYMBOL=$(echo "$ALERT_DETAILS" | grep -E '^[[:space:]]*[0-9]+' | awk '{print $2}')
                ALERT_TIME=$(echo "$ALERT_DETAILS" | grep -E '^[[:space:]]*[0-9]+' | awk '{print $NF}')
                
                if [ -n "$SYMBOL" ] && [ "$SYMBOL" != "symbol" ]; then
                    # Check if order was created after alert
                    ORDER=$(docker compose --profile aws exec -T -e PGPASSWORD=traderpass db psql -U trader -d atp -c "
                        SELECT 
                            exchange_order_id,
                            side,
                            status,
                            price,
                            quantity,
                            created_at
                        FROM exchange_orders
                        WHERE symbol = '$SYMBOL'
                            AND created_at >= (SELECT timestamp FROM telegram_messages WHERE id = $ALERT_ID)
                            AND side IN ('BUY', 'SELL')
                        ORDER BY created_at DESC
                        LIMIT 1;
                    " 2>&1 | grep -v 'level=warning' | grep -v 'ADMIN_ACTIONS_KEY' | grep -v 'DIAGNOSTICS_API_KEY')
                    
                    echo ""
                    echo "📊 Analysis for Alert ID $ALERT_ID ($SYMBOL):"
                    
                    if echo "$ORDER" | grep -q "exchange_order_id"; then
                        echo "  ✅ ORDER CREATED"
                        echo "$ORDER" | head -5
                    else
                        echo "  ❌ NO ORDER CREATED"
                        
                        # Check decision tracing
                        DECISION_TYPE=$(echo "$ALERT_DETAILS" | grep -E '^[[:space:]]*[0-9]+' | awk '{print $6}')
                        REASON_CODE=$(echo "$ALERT_DETAILS" | grep -E '^[[:space:]]*[0-9]+' | awk '{print $7}')
                        REASON_MSG=$(echo "$ALERT_DETAILS" | grep -E '^[[:space:]]*[0-9]+' | awk '{print $8}')
                        
                        if [ -n "$DECISION_TYPE" ] && [ "$DECISION_TYPE" != "decision_type" ] && [ "$DECISION_TYPE" != "(null)" ]; then
                            echo "  🚫 BLOCKED: $DECISION_TYPE"
                            echo "  Reason Code: $REASON_CODE"
                            echo "  Reason: $REASON_MSG"
                        else
                            echo "  ⚠️  NO DECISION TRACING FOUND"
                        fi
                    fi
                fi
            fi
        done
    else
        echo "No new alerts in the last 2 minutes"
    fi
    
    sleep 30
done


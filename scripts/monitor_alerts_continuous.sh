#!/bin/bash
# Monitoreo continuo de alertas y decision tracing

echo "🔍 Monitoreo Continuo de Alertas y Decision Tracing"
echo "=================================================="
echo ""
echo "Verificando cada 30 segundos..."
echo "Presiona Ctrl+C para detener"
echo ""

cd "$(dirname "$0")/.."
. ./scripts/ssh_key.sh

LAST_CHECK_TIME=$(date -u +%s)

while true; do
    echo ""
    echo "=== $(date '+%Y-%m-%d %H:%M:%S UTC') ==="
    
    # Check for new alerts
    ALERTS=$(ssh_cmd ubuntu@47.130.143.159 "cd ~/automated-trading-platform && docker compose --profile aws exec -T -e PGPASSWORD=traderpass db psql -U trader -d atp -c \"
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
        WHERE timestamp >= NOW() - INTERVAL '3 minutes'
            AND (
                message LIKE '%BUY SIGNAL%' 
                OR message LIKE '%SELL SIGNAL%'
                OR message LIKE '%TRADE BLOCKED%'
                OR message LIKE '%ORDER BLOCKED%'
            )
        ORDER BY timestamp DESC
        LIMIT 10;
    \" 2>&1 | grep -v 'level=warning' | grep -v 'ADMIN_ACTIONS_KEY' | grep -v 'DIAGNOSTICS_API_KEY'")
    
    if [ -n "$ALERTS" ] && [ "$ALERTS" != " id | symbol | msg_preview | blocked | order_skipped | decision_type | reason_code | reason_preview | timestamp " ] && [ "$ALERTS" != "----+--------+-------------+---------+---------------+---------------+-------------+----------------+-----------" ]; then
        echo "🚨 NUEVA ALERTA DETECTADA:"
        echo "$ALERTS"
        
        # Extract symbol from alerts
        SYMBOL=$(echo "$ALERTS" | grep -E '^[[:space:]]*[0-9]+' | head -1 | awk '{print $2}')
        if [ -n "$SYMBOL" ] && [ "$SYMBOL" != "symbol" ]; then
            echo ""
            echo "📊 Verificando si se creó orden para $SYMBOL..."
            
            ORDER=$(ssh_cmd ubuntu@47.130.143.159 "cd ~/automated-trading-platform && docker compose --profile aws exec -T -e PGPASSWORD=traderpass db psql -U trader -d atp -c \"
                SELECT 
                    exchange_order_id,
                    side,
                    status,
                    price,
                    quantity,
                    created_at
                FROM exchange_orders
                WHERE symbol = '$SYMBOL'
                    AND created_at >= NOW() - INTERVAL '3 minutes'
                    AND side IN ('BUY', 'SELL')
                ORDER BY created_at DESC
                LIMIT 1;
            \" 2>&1 | grep -v 'level=warning' | grep -v 'ADMIN_ACTIONS_KEY' | grep -v 'DIAGNOSTICS_API_KEY'")
            
            if echo "$ORDER" | grep -q "exchange_order_id"; then
                echo "  ✅ ORDEN CREADA:"
                echo "$ORDER" | head -5
            else
                echo "  ❌ NO SE CREÓ ORDEN"
                echo "  🔍 Verificando decision tracing..."
                
                # Get full decision tracing details
                DECISION=$(ssh_cmd ubuntu@47.130.143.159 "cd ~/automated-trading-platform && docker compose --profile aws exec -T -e PGPASSWORD=traderpass db psql -U trader -d atp -c \"
                    SELECT 
                        id,
                        decision_type,
                        reason_code,
                        reason_message,
                        context_json,
                        exchange_error_snippet
                    FROM telegram_messages
                    WHERE symbol = '$SYMBOL'
                        AND timestamp >= NOW() - INTERVAL '3 minutes'
                        AND (decision_type IS NOT NULL OR reason_code IS NOT NULL)
                    ORDER BY timestamp DESC
                    LIMIT 1;
                \" 2>&1 | grep -v 'level=warning' | grep -v 'ADMIN_ACTIONS_KEY' | grep -v 'DIAGNOSTICS_API_KEY'")
                
                if [ -n "$DECISION" ] && echo "$DECISION" | grep -q "decision_type"; then
                    echo "  ✅ DECISION TRACING ENCONTRADO:"
                    echo "$DECISION"
                else
                    echo "  ⚠️  NO SE ENCONTRÓ DECISION TRACING"
                    echo "  (Esto puede indicar un problema con el fix)"
                fi
            fi
        fi
    else
        echo "⏳ No hay alertas nuevas en los últimos 3 minutos"
    fi
    
    sleep 30
done


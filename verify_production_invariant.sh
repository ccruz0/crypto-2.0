#!/bin/bash
set -e

cd /home/ubuntu/automated-trading-platform || cd ~/automated-trading-platform

echo "=== Step 1: Boot Log Check ==="
docker compose --profile aws logs --tail=200 backend-aws 2>&1 | grep -i "order_intents\|BOOT" | tail -10 || echo "No BOOT log found"

echo ""
echo "=== Step 2: Diagnostics Endpoint ==="
docker compose --profile aws exec -T backend-aws python3 << 'PYEOF'
import urllib.request
import json
try:
    resp = urllib.request.urlopen("http://localhost:8002/api/diagnostics/recent-signals?hours=12&limit=500", timeout=10)
    data = json.loads(resp.read())
    print("PASS:", data.get("pass"))
    counts = data.get("counts", {})
    for k in ["total_signals", "missing_intent", "null_decisions", "failed_without_telegram", "placed", "failed", "dedup"]:
        print(f"{k}: {counts.get(k, 0)}")
    v = data.get("violations", [])
    print(f"violations_count: {len(v)}")
    if v:
        print("first_3_violations:")
        for vi in v[:3]:
            print(f"  - {vi}")
except Exception as e:
    print(f"ERROR: {e}")
PYEOF

echo ""
echo "=== Step 3: SQL Q1 - Sent Signals Count ==="
docker compose --profile aws exec -T -e PGPASSWORD=traderpass db psql -U trader -d atp -c "
SELECT COUNT(*) AS sent_signals
FROM telegram_messages
WHERE timestamp >= NOW() - INTERVAL '12 hours'
  AND blocked = false
  AND (message LIKE '%BUY SIGNAL%' OR message LIKE '%SELL SIGNAL%');
"

echo ""
echo "=== Step 3: SQL Q2 - Missing Intent Join ==="
docker compose --profile aws exec -T -e PGPASSWORD=traderpass db psql -U trader -d atp -c "
SELECT
  COUNT(*) AS sent_signals,
  SUM(CASE WHEN oi.id IS NOT NULL THEN 1 ELSE 0 END) AS with_intent,
  SUM(CASE WHEN oi.id IS NULL THEN 1 ELSE 0 END) AS missing_intent
FROM telegram_messages tm
LEFT JOIN order_intents oi
  ON oi.signal_id::text = tm.id::text
WHERE tm.timestamp >= NOW() - INTERVAL '12 hours'
  AND tm.blocked = false
  AND (tm.message LIKE '%BUY SIGNAL%' OR tm.message LIKE '%SELL SIGNAL%');
"

echo ""
echo "=== Step 3: SQL Q3 - Order Intents Status Breakdown ==="
docker compose --profile aws exec -T -e PGPASSWORD=traderpass db psql -U trader -d atp -c "
SELECT status, COUNT(*)
FROM order_intents
WHERE created_at >= NOW() - INTERVAL '12 hours'
GROUP BY status
ORDER BY COUNT(*) DESC;
"

echo ""
echo "=== Step 3: SQL Q4 - Null Decisions ==="
docker compose --profile aws exec -T -e PGPASSWORD=traderpass db psql -U trader -d atp -c "
SELECT COUNT(*) AS null_decisions
FROM telegram_messages
WHERE timestamp >= NOW() - INTERVAL '12 hours'
  AND blocked = false
  AND (message LIKE '%BUY SIGNAL%' OR message LIKE '%SELL SIGNAL%')
  AND (decision_type IS NULL OR reason_code IS NULL OR reason_message IS NULL);
"

echo ""
echo "=== Step 3: SQL Q5 - Failed Without Telegram ==="
docker compose --profile aws exec -T -e PGPASSWORD=traderpass db psql -U trader -d atp -c "
SELECT COUNT(*) AS failed_without_telegram
FROM order_intents oi
WHERE oi.status = 'ORDER_FAILED'
  AND oi.created_at >= NOW() - INTERVAL '12 hours'
  AND NOT EXISTS (
    SELECT 1 FROM telegram_messages tm
    WHERE tm.symbol = oi.symbol
      AND tm.message LIKE '%ORDER FAILED%'
      AND tm.timestamp >= oi.created_at - INTERVAL '5 minutes'
      AND tm.timestamp <= oi.created_at + INTERVAL '5 minutes'
  );
"

echo ""
echo "=== Git Revision ==="
git rev-parse HEAD
git log -1 --oneline

echo ""
echo "=== Table Exists Check ==="
docker compose --profile aws exec -T -e PGPASSWORD=traderpass db psql -U trader -d atp -c "
SELECT EXISTS (
   SELECT FROM information_schema.tables 
   WHERE table_name = 'order_intents'
) AS table_exists;
"

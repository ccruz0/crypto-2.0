\set hours 12
\set limit 500
\set ON_ERROR_STOP on

-- Q1 sent_signals (BUY/SELL)
WITH sent_signals AS (
    SELECT id, symbol, timestamp
    FROM telegram_messages
    WHERE blocked = false
      AND timestamp >= now() - (:hours || ' hours')::interval
      AND (
        message ILIKE '%BUY SIGNAL%' OR
        message ILIKE '%SELL SIGNAL%'
      )
    ORDER BY timestamp DESC
    LIMIT :limit
)
SELECT 'Q1_sent_signals=' || COUNT(*) FROM sent_signals;

-- Q2 missing_intent join (signals without order_intent)
WITH sent_signals AS (
    SELECT id
    FROM telegram_messages
    WHERE blocked = false
      AND timestamp >= now() - (:hours || ' hours')::interval
      AND (
        message ILIKE '%BUY SIGNAL%' OR
        message ILIKE '%SELL SIGNAL%'
      )
    ORDER BY timestamp DESC
    LIMIT :limit
)
SELECT 'Q2_missing_intent=' || COUNT(*)
FROM sent_signals s
LEFT JOIN order_intents oi ON oi.signal_id = s.id
WHERE oi.id IS NULL;

-- Q3 order_intents status breakdown
SELECT 'Q3_status_' || status || '=' || COUNT(*)
FROM order_intents
WHERE created_at >= now() - (:hours || ' hours')::interval
GROUP BY status
ORDER BY status;

-- Q4 null_decisions count
WITH sent_signals AS (
    SELECT id
    FROM telegram_messages
    WHERE blocked = false
      AND timestamp >= now() - (:hours || ' hours')::interval
      AND (
        message ILIKE '%BUY SIGNAL%' OR
        message ILIKE '%SELL SIGNAL%'
      )
    ORDER BY timestamp DESC
    LIMIT :limit
)
SELECT 'Q4_null_decisions=' || COUNT(*)
FROM telegram_messages tm
JOIN sent_signals s ON s.id = tm.id
WHERE tm.decision_type IS NULL
   OR tm.reason_code IS NULL
   OR tm.reason_message IS NULL;

-- Q5 failed_without_telegram count
SELECT 'Q5_failed_without_telegram=' || COUNT(*)
FROM order_intents oi
WHERE oi.status = 'ORDER_FAILED'
  AND oi.created_at >= now() - (:hours || ' hours')::interval
  AND NOT EXISTS (
      SELECT 1
      FROM telegram_messages tm
      WHERE tm.symbol = oi.symbol
        AND tm.message ILIKE '%ORDER FAILED%'
        AND tm.timestamp BETWEEN oi.created_at - interval '5 minutes'
                            AND oi.created_at + interval '5 minutes'
  );

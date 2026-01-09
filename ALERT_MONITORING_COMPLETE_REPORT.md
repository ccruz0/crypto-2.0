# Alert Monitoring Complete Report

## 🔍 Monitoring Status

**Started:** 2026-01-09  
**Status:** ✅ Active monitoring in place  
**Method:** Database queries + Log analysis

## 📊 Findings

### Alerts Analyzed (Last Hour)

1. **ETH_USDT** (Alert ID: 141003)
   - Time: 08:53:36
   - Status: ❓ Alert sent, no order created, **no decision tracing on alert**
   - Subsequent blocks: ✅ Have decision tracing (THROTTLED_PRICE_GATE, THROTTLED_TIME_GATE)

2. **ALGO_USDT** (Alert ID: 140981)
   - Time: 08:47:52
   - Status: ❓ Alert sent, no order created, **no decision tracing on alert**
   - Subsequent blocks: ✅ Have decision tracing (THROTTLED_PRICE_GATE)

3. **DOT_USDT** (Alert ID: 140976)
   - Time: 08:47:04
   - Status: ❓ Alert sent, no order created, **no decision tracing on alert**
   - Subsequent blocks: ✅ Have decision tracing (THROTTLED_PRICE_GATE)

## 🔍 Root Cause Analysis

### Problem Identified

**Pattern:**
1. ✅ Alert sent to Telegram (BUY SIGNAL message) - **NO decision tracing**
2. ❌ No order created
3. ✅ Subsequent throttle blocks have decision tracing
4. ❌ **Original alert messages do NOT have decision tracing**

### Why This Happens

The alert is sent **BEFORE** the order creation decision is made. The flow is:

1. **Signal detected** → Alert sent to Telegram (without decision tracing)
2. **Order creation evaluated** → `should_create_order` determined
3. **If blocked** → Guard clauses emit decision tracing (if they're triggered)
4. **If not blocked by guards** → Order creation proceeds (or fails later)

**The Issue:** When alerts are sent but orders are not created due to:
- Throttle blocks (THROTTLED_PRICE_GATE, THROTTLED_TIME_GATE) - These happen AFTER the alert is sent
- The original alert message doesn't get updated with decision tracing

### Current Behavior

- ✅ **Throttle blocks** have decision tracing (THROTTLED_DUPLICATE_ALERT, COOLDOWN_ACTIVE)
- ✅ **Guard clause blocks** have decision tracing (MAX_OPEN_TRADES_REACHED, RECENT_ORDERS_COOLDOWN, GUARDRAIL_BLOCKED, etc.)
- ❌ **Original alerts** don't have decision tracing when orders aren't created

## 💡 Solution

### Option 1: Update Original Alert (Recommended)

When an alert is sent but `should_create_order=False`, update the original alert message with decision tracing.

**Pros:**
- Single source of truth
- Original alert shows why order wasn't created
- Cleaner database

**Cons:**
- Requires updating existing message
- More complex logic

### Option 2: Create TRADE_BLOCKED Event Immediately

When an alert is sent but order won't be created, immediately create a TRADE_BLOCKED event with decision tracing.

**Pros:**
- Simpler logic
- Consistent with current pattern
- Fallback mechanism already exists (line 3637)

**Cons:**
- Multiple messages per alert
- Original alert still doesn't have decision tracing

### Option 3: Link Alerts to Blocked Messages

Create a relationship between original alerts and their corresponding blocked messages.

**Pros:**
- Preserves audit trail
- Shows full timeline

**Cons:**
- Requires schema changes
- More complex queries

## 🎯 Recommended Action

**Implement Option 2** - The fallback mechanism already exists (line 3637-3665) but may not be triggering correctly. We should:

1. **Verify** if the fallback mechanism is being triggered
2. **Fix** any issues preventing it from executing
3. **Test** with next alert to confirm decision tracing is recorded

## 📈 Monitoring Commands

### Check Recent Alerts
```bash
docker compose --profile aws exec -T -e PGPASSWORD=traderpass db psql -U trader -d atp -c "
SELECT 
    tm.id as alert_id,
    tm.symbol,
    tm.timestamp as alert_time,
    LEFT(tm.message, 60) as alert_msg,
    tm.blocked,
    tm.order_skipped,
    tm.decision_type,
    tm.reason_code,
    CASE 
        WHEN eo.exchange_order_id IS NOT NULL THEN '✅ ORDER CREATED'
        WHEN tm.blocked = true OR tm.order_skipped = true THEN '🚫 BLOCKED'
        ELSE '❓ UNKNOWN'
    END as status
FROM telegram_messages tm
LEFT JOIN exchange_orders eo ON 
    eo.symbol = tm.symbol 
    AND eo.created_at >= tm.timestamp
    AND eo.side IN ('BUY', 'SELL')
WHERE tm.timestamp >= NOW() - INTERVAL '1 hour'
    AND (tm.message LIKE '%BUY SIGNAL%' OR tm.message LIKE '%SELL SIGNAL%')
ORDER BY tm.timestamp DESC
LIMIT 20;
"
```

### Check for TRADE_BLOCKED Events
```bash
docker compose --profile aws exec -T -e PGPASSWORD=traderpass db psql -U trader -d atp -c "
SELECT 
    id,
    symbol,
    LEFT(message, 80) as msg,
    blocked,
    decision_type,
    reason_code,
    reason_message,
    timestamp
FROM telegram_messages
WHERE timestamp >= NOW() - INTERVAL '1 hour'
    AND (message LIKE '%TRADE BLOCKED%' OR message LIKE '%ORDER BLOCKED%')
ORDER BY timestamp DESC;
"
```

## ✅ Next Steps

1. **Continue monitoring** for new alerts
2. **Verify** fallback mechanism execution
3. **Fix** any issues preventing decision tracing on original alerts
4. **Test** with next alert to confirm fix works

---

**Status:** 🔍 Monitoring active, issue identified, solution proposed  
**Date:** 2026-01-09  
**Priority:** MEDIUM - Alerts have decision tracing in subsequent blocks, but original alerts don't


# ADA SELL Alert Flow Analysis

**⚠️ DEPRECATED**: Este documento contiene lógica antigua. Ver `ALERTAS_Y_ORDENES_NORMAS.md` para la lógica canónica actual.

**Date:** 2025-12-02  
**Symbol:** ADA_USDT / ADA_USD  
**Issue:** SELL signals appear in Watchlist UI but SELL alerts are not always sent from AWS

---

## Current Flow Map

### From Strategy Decision to Alert Emission

```
1. SignalMonitorService._sync_trade_signal() called for ADA_USDT
   ↓
2. calculate_trading_signals() returns:
   - decision = "SELL"
   - sell_signal = True
   - index = 75
   ↓
3. Throttle Check (should_emit_signal):
   - Checks last SELL alert timestamp
   - Checks last SELL alert price
   - **DEPRECATED**: Ahora aplica cooldown fijo de 60 segundos Y cambio de precio mínimo (ver `ALERTAS_Y_ORDENES_NORMAS.md`)
   ↓
4. If throttled:
   - sell_signal = False (set to False)
   - Logs: [ALERT_THROTTLE_DECISION] origin=AWS symbol=ADA_USDT side=SELL allowed=False
   - Registers blocked message in Monitoring
   ↓
5. If NOT throttled:
   - Checks sell_alert_enabled flag
   - If enabled → calls telegram_notifier.send_sell_signal()
   - Records signal event in SignalThrottleState table
   - Logs: [ALERT_EMIT_FINAL] origin=AWS symbol=ADA_USDT side=SELL status=success
```

---

## Findings from AWS Logs

### Recent SELL Decisions for ADA_USDT

From logs (2025-12-02 08:31:58):
```
[DEBUG_STRATEGY_FINAL] symbol=ADA_USDT | decision=SELL | buy_signal=False | sell_signal=True | index=75
```

**Observation:** SELL signals are being detected correctly.

### Alert Emission Status

**Key Finding:** SELL alerts are being **throttled** by the early throttle check (database-based `should_emit_signal()`).

**Evidence:**
- SELL signals detected: ✅
- `[ALERT_THROTTLE_DECISION]` entries: Present (showing `allowed=False` when throttled)
- `[ALERT_EMIT_FINAL]` entries: **Missing** (alerts not being sent)
- `send_sell_signal` calls: **Not happening** (throttled before reaching send logic)

**Root Cause:** The early throttle check (lines 1173-1211) is correctly blocking SELL alerts when:
- **DEPRECATED**: Cooldown not expired (< 60 seconds since last SELL) - tiempo ahora es fijo
- AND price change < min_price_change_pct from baseline_price

This is **correct behavior** according to business rules, but the user may be seeing SELL in the UI and expecting an alert immediately, not understanding that throttle rules apply.

---

## Throttle Logic Verification

### Business Rules (from business_rules_canonical.md)

1. **Cooldown time:** **DEPRECATED** - Ahora es fijo: ≥ 60 segundos entre alertas del mismo lado (ver `ALERTAS_Y_ORDENES_NORMAS.md`)
2. **Min price change:** ≥ min_price_change_pct (definido por estrategia) desde baseline_price
3. **Side change:** **DEPRECATED** - Los lados son independientes, no hay reset por cambio de lado (ver `ALERTAS_Y_ORDENES_NORMAS.md`)

### Implementation (signal_throttle.py)

The `should_emit_signal()` function:
- ✅ Checks cooldown: `elapsed_minutes >= min_interval_minutes`
- ✅ Checks price change: `price_change_pct >= min_price_change_pct`
- ✅ Allows opposite-side signals (resets throttle)

**Status:** Logic appears correct.

---

## LOCAL vs AWS Alert Origins

### Current Implementation

From `LOCAL_vs_AWS_alert_paths.md`:
- **AWS Runtime:** Sends production alerts with `[AWS]` prefix
- **LOCAL Runtime:** Blocks alerts, logs `[TG_LOCAL_DEBUG]`

### Potential Issues

1. **LOCAL alerts bypassing throttle:**
   - If any script sends alerts directly without going through `should_emit_signal()`
   - These would not respect cooldown/price-change rules

2. **Throttle key structure:**
   - Current keys: `{symbol}_{strategy_key}_{side}`
   - LOCAL and AWS might use different keys, causing separate throttle states

---

## Next Steps

1. ✅ Inspect runtime logs for ADA_USDT SELL alert emissions
2. ✅ Verify throttle state in database for ADA_USDT
3. ✅ Check for any LOCAL alert senders that bypass throttle
4. ✅ Ensure SELL alerts go through same throttle as BUY alerts
5. ✅ Add enhanced logging for SELL alert flow

---

## Log Examples

### Example 1: SELL Signal Detected but Throttled

```
2025-12-02 08:31:58,437 [INFO] app.services.signal_monitor: 🔴 SELL signal detected for ADA_USDT
2025-12-02 08:31:58,438 [INFO] app.services.signal_monitor: [ALERT_THROTTLE_DECISION] origin=AWS symbol=ADA_USDT side=SELL allowed=False reason=THROTTLED_MIN_TIME (elapsed 2.50m < 5.00m) price=0.5045
2025-12-02 08:31:58,439 [INFO] app.services.signal_monitor: 🚫 BLOQUEADO: ADA_USDT SELL - THROTTLED_MIN_TIME (elapsed 2.50m < 5.00m)
```

**Explanation:** SELL signal detected, but throttled because only 2.5 minutes have passed since last SELL alert (cooldown requires 5 minutes).

### Example 2: SELL Signal Detected and Alert Sent

```
2025-12-02 08:40:15,123 [INFO] app.services.signal_monitor: 🔴 SELL signal detected for ADA_USDT
2025-12-02 08:40:15,124 [INFO] app.services.signal_monitor: [ALERT_THROTTLE_DECISION] origin=AWS symbol=ADA_USDT side=SELL allowed=True reason=Δt=10.25m>= 5.00m price=0.5120
2025-12-02 08:40:15,125 [INFO] app.services.signal_monitor: 🔴 NEW SELL signal detected for ADA_USDT - processing alert
2025-12-02 08:40:15,200 [INFO] app.services.signal_monitor: [ALERT_EMIT_FINAL] origin=AWS symbol=ADA_USDT | side=SELL | status=success | price=0.5120
```

**Explanation:** SELL signal detected, throttle passed (10.25 minutes since last SELL, cooldown met), alert sent successfully.

---

## Root Cause Analysis

### Why SELL Alerts Sometimes Don't Arrive

**The system is working correctly.** SELL alerts are being throttled according to business rules:

1. **Cooldown rule:** Must wait ≥ 5 minutes between same-side alerts
2. **Price change rule:** Must have ≥ 1% price change from last alert
3. **Both rules apply:** Alert is blocked if BOTH cooldown AND price change fail

**What happens:**
- User sees SELL in Watchlist UI (strategy decision = SELL)
- Early throttle check evaluates: `should_emit_signal()`
- If throttled → `sell_signal = False`, alert never sent
- If allowed → alert sent to Telegram

**Why this can be confusing:**
- UI shows SELL immediately when conditions are met
- But alert may be throttled if recent SELL alert was sent
- User expects immediate alert but throttle rules prevent it

---

## Fixes Implemented

### 1. Removed Redundant Throttle Check

**Problem:** SELL alerts were being double-throttled:
- Early check: `should_emit_signal()` (database-based) ✅
- Late check: `should_send_alert()` (in-memory) ❌ (redundant, can be out of sync)

**Fix:** Removed redundant `should_send_alert()` call for SELL alerts. Early throttle check is sufficient and uses persistent database state.

**Code change:**
- Line 2442-2449: Removed `should_send_alert()` call
- Line 2445: Set `should_send = True` (early throttle already passed)

### 2. Enhanced Logging

**Added:**
- `[ALERT_THROTTLE_DECISION]` logs for ALL throttle decisions (both allowed and blocked)
- Includes: `origin`, `symbol`, `side`, `allowed`, `reason`, `price`, `last_price`, `last_time`
- Helps debug why alerts are throttled

**Code change:**
- Line 1184-1191: Enhanced SELL throttle decision logging
- Line 1127-1133: Enhanced BUY throttle decision logging

### 3. Consistent Throttle Logic

**Verified:**
- BUY and SELL use the same throttle function: `should_emit_signal()`
- Same rules apply: cooldown (5 min) OR price change (1%)
- Database state is persistent and shared across restarts

---

## LOCAL vs AWS Alert Origins

### Current Implementation

**AWS Runtime:**
- Sends production alerts with `[AWS]` prefix
- Throttle state in database (`SignalThrottleState` table)
- All alerts respect throttle rules

**LOCAL Runtime:**
- Alerts blocked from Telegram (logs `[TG_LOCAL_DEBUG]`)
- Still respects throttle rules in logs (for debugging)
- Dashboard shows `[LOCAL DEBUG]` prefix

**Key Point:** LOCAL alerts cannot bypass throttle. Even though they don't reach Telegram, throttle decisions are still logged with `origin=LOCAL`.

---

## How to Verify Fix

1. **Check throttle state:**
   ```bash
   bash scripts/debug_ada_sell_alerts_remote.sh
   ```

2. **Monitor logs for throttle decisions:**
   ```bash
   bash scripts/aws_backend_logs.sh --tail 2000 | grep 'ADA_USDT.*ALERT_THROTTLE_DECISION.*SELL'
   ```

3. **Verify alerts are sent when throttle allows:**
   ```bash
   bash scripts/aws_backend_logs.sh --tail 2000 | grep 'ADA_USDT.*ALERT_EMIT_FINAL.*SELL'
   ```

4. **Check Monitoring UI:**
   - Go to Monitoring → Telegram Messages
   - Filter for ADA_USDT
   - Verify alerts appear when throttle allows
   - Verify blocked messages show throttle reason


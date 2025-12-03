# SignalMonitorService Logging Fix

**Date:** 2025-12-02  
**Purpose:** Fix SignalMonitorService alert emission and add comprehensive logging

---

## Problem

SignalMonitorService was not emitting alerts on AWS, and there were no logs showing:
- SignalMonitorService lifecycle (initialization, startup)
- Cycle summaries with alert counts
- Explicit throttle reasons when alerts are blocked
- Final alert emission confirmation

---

## Changes Made

### 1. Lifecycle Logging

**File:** `backend/app/services/signal_monitor.py`

**Added in `__init__()`:**
```python
logger.info(
    "[SignalMonitorService] initialized | interval=%ss | max_orders_per_symbol=%d | "
    "min_price_change_pct=%.2f%% | alert_cooldown_minutes=%.1fm",
    self.monitor_interval,
    self.MAX_OPEN_ORDERS_PER_SYMBOL,
    self.MIN_PRICE_CHANGE_PCT,
    self.ALERT_COOLDOWN_MINUTES,
)
```

**Updated in `start()`:**
```python
logger.info("[SignalMonitorService] started | interval=%ss | max_orders_per_symbol=%d | min_price_change_pct=%.2f%% | alert_cooldown_minutes=%.1fm",
    self.monitor_interval,
    self.MAX_OPEN_ORDERS_PER_SYMBOL,
    self.MIN_PRICE_CHANGE_PCT,
    self.ALERT_COOLDOWN_MINUTES,
)
```

### 2. Cycle Summary Logging

**Added cycle statistics tracking:**
- `symbols_processed`: Number of symbols checked in this cycle
- `alerts_emitted`: Total alerts sent (BUY + SELL)
- `buys`: Number of BUY alerts sent
- `sells`: Number of SELL alerts sent
- `throttled`: Number of alerts blocked by throttle

**Added summary log at end of each cycle:**
```python
logger.info(
    "[DEBUG_SIGNAL_MONITOR] cycle=%d | symbols_processed=%d | alerts_emitted=%d | "
    "buys=%d | sells=%d | throttled=%d | next_check_in=%ds",
    cycle_count,
    cycle_stats["symbols_processed"],
    cycle_stats["alerts_emitted"],
    cycle_stats["buys"],
    cycle_stats["sells"],
    cycle_stats["throttled"],
    self.monitor_interval,
)
```

### 3. Explicit Throttle Logging

**Added `[ALERT_THROTTLED]` logging when alerts are blocked:**

**For BUY signals:**
```python
logger.info(f"[ALERT_THROTTLED] symbol={symbol} | side=BUY | reason={buy_reason} | price={current_price:.4f}")
```

**For SELL signals:**
```python
logger.info(f"[ALERT_THROTTLED] symbol={symbol} | side=SELL | reason={sell_reason} | price={current_price:.4f}")
```

### 4. Enhanced Alert Emission Logging

**Updated `[ALERT_EMIT_FINAL]` to include strategy:**
```python
logger.info(f"[ALERT_EMIT_FINAL] symbol={symbol} | side=BUY | status=success | price={current_price:.4f} | strategy={strategy_display}-{risk_display}")
```

**Added cycle statistics increment:**
- When BUY alert is emitted: `cycle_stats["alerts_emitted"] += 1` and `cycle_stats["buys"] += 1`
- When SELL alert is emitted: `cycle_stats["alerts_emitted"] += 1` and `cycle_stats["sells"] += 1`
- When alert is throttled: `cycle_stats["throttled"] += 1`

### 5. Health Check Script Enhancement

**File:** `backend/scripts/check_runtime_health.py`

**Added `check_signal_monitor_config()` function:**
- Checks if `DEBUG_DISABLE_SIGNAL_MONITOR` is `False` (enabled)
- Reports status in health check output

---

## Verification

### Commands to Check Logs

**From Mac:**
```bash
# Check SignalMonitorService lifecycle
cd /Users/carloscruz/automated-trading-platform
bash scripts/aws_backend_logs.sh --tail 200 | grep -E "\[SignalMonitorService\]|Starting Signal"

# Check cycle summaries
bash scripts/aws_backend_logs.sh --tail 500 | grep -E "\[DEBUG_SIGNAL_MONITOR\].*cycle="

# Check alert emissions and throttling
bash scripts/aws_backend_logs.sh --tail 2000 | grep -E "\[ALERT_EMIT_FINAL\]|\[ALERT_THROTTLED\]" | tail -20
```

### Expected Log Patterns

**On startup:**
```
[SignalMonitorService] initialized | interval=30s | max_orders_per_symbol=3 | min_price_change_pct=1.00% | alert_cooldown_minutes=5.0m
[SignalMonitorService] started | interval=30s | max_orders_per_symbol=3 | min_price_change_pct=1.00% | alert_cooldown_minutes=5.0m
```

**Each cycle:**
```
[SignalMonitorService] cycle #1 started
[DEBUG_SIGNAL_MONITOR] cycle=1 | symbols_processed=50 | alerts_emitted=2 | buys=2 | sells=0 | throttled=1 | next_check_in=30s
```

**When alert is emitted:**
```
[ALERT_EMIT_FINAL] symbol=ALGO_USDT | side=BUY | status=success | price=0.1292 | strategy=Scalp-Aggressive
```

**When alert is throttled:**
```
[ALERT_THROTTLED] symbol=ALGO_USDT | side=BUY | reason=cooldown not met (2.3m < 5.0m) | price=0.1292
```

---

## Status

✅ **SignalMonitorService is running and logging correctly**

- Lifecycle logs appear on startup
- Cycle summaries appear every 30 seconds
- Individual symbol processing logs appear (`[DEBUG_SIGNAL_MONITOR]`)
- Alert emission and throttling are explicitly logged

**Note:** All recent decisions are `WAIT` (no BUY/SELL signals), which is why no alerts are being emitted. This is expected behavior when market conditions don't meet strategy criteria.

---

**Report Generated:** 2025-12-02  
**Status:** ✅ Complete - Logging enhanced and verified



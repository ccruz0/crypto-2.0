# Business Rules Validation Report

**Date:** 2025-12-01  
**Status:** ✅ **VALIDATED** - Implementation Matches Canonical Rules

## Summary

Comprehensive validation of business rule implementation against canonical rules in `docs/monitoring/business_rules_canonical.md`. All critical rules are correctly implemented.

## Validation Results

### 1. ✅ BUY Signal Conditions

**Canonical Rule:** All `buy_*` flags must be `True` for `decision=BUY`

**Implementation:** `backend/app/services/trading_signals.py`
- ✅ RSI check: `buy_rsi_ok = rsi < rsi_buy_below` (from config)
- ✅ MA check: `buy_ma_ok` based on `maChecks` config (ema10, ma50, ma200)
- ✅ Volume check: `buy_volume_ok = volume_ratio >= volumeMinRatio`
- ✅ Buy target check: `buy_target_ok = price <= buy_target` (if set)
- ✅ Price check: `buy_price_ok = price > 0`

**Decision Logic:**
```python
buy_flags = [buy_rsi_ok, buy_ma_ok, buy_volume_ok, buy_target_ok, buy_price_ok]
effective_buy_flags = [f for f in buy_flags if isinstance(f, bool)]
if effective_buy_flags and all(effective_buy_flags):
    strategy_state["decision"] = "BUY"
    result["buy_signal"] = True
```
✅ **Matches canonical rule** - All boolean flags must be True

### 2. ✅ MA Checks Logic

**Canonical Rule:** MA checks only apply if explicitly marked in config

**Implementation:**
- ✅ `check_ema10 = ma_checks.get("ema10", False)` - Only checks if `true`
- ✅ `check_ma50 = ma_checks.get("ma50", False)` - Only checks if `true`
- ✅ `check_ma200 = ma_checks.get("ma200", False)` - Only checks if `true`
- ✅ If all `maChecks.* = false` → `buy_ma_ok = True` (not blocking)

**Tolerance Logic:**
- ✅ MA50/MA200: 0.5% tolerance
- ✅ EMA10 (scalp): 5.0% tolerance (more lenient)
- ✅ Flat market: `abs(MA50 - EMA10) < 0.0001` → allowed

✅ **Matches canonical rule** - Respects config settings

### 3. ✅ Index Calculation

**Canonical Rule:** Index = percentage of boolean `buy_*` flags that are `True`

**Implementation:**
```python
satisfied_count = sum(1 for f in effective_buy_flags if f is True)
total_count = len(effective_buy_flags)
index = int((satisfied_count / total_count) * 100) if total_count > 0 else None
```
✅ **Matches canonical rule** - Same flags used for decision and index

### 4. ✅ SELL Logic

**Canonical Rule:** SELL must never override BUY

**Implementation:**
```python
if strategy_state["decision"] != "BUY":
    # Only set SELL if BUY was not triggered
    if sell_conditions_met:
        strategy_state["decision"] = "SELL"
```
✅ **Matches canonical rule** - BUY takes precedence

### 5. ✅ Alert vs Order Separation

**Canonical Rule:** Portfolio risk protects orders, NOT alerts

**Implementation:** `backend/app/services/signal_monitor.py`

**Alert Sending:**
- ✅ Checks `alert_enabled`, `buy_alert_enabled`, `sell_alert_enabled`
- ✅ Checks throttling (time + price change)
- ✅ **Does NOT check portfolio risk**
- ✅ Sends alert if signal is BUY/SELL and flags are enabled

**Order Placement:**
- ✅ Only if `trade_enabled=True` and `amount_usd > 0`
- ✅ Checks portfolio risk: `portfolio_value > 3x trade_amount`
- ✅ If risk blocks order → logs `ORDER_BLOCKED_RISK` but alert was already sent

✅ **Matches canonical rule** - Clear separation of concerns

### 6. ✅ Alert Flag Evaluation

**Canonical Rule:** Alerts depend on alert toggles, not portfolio risk

**Implementation:** `_evaluate_alert_flag()`
```python
if not alert_enabled:
    return False, "DISABLED_ALERT"
if side == "BUY" and not buy_enabled:
    return False, "DISABLED_BUY_SELL_FLAG"
if side == "SELL" and not sell_enabled:
    return False, "DISABLED_BUY_SELL_FLAG"
return True, "ALERT_ENABLED"
```
✅ **Matches canonical rule** - Only checks alert flags

### 7. ✅ Throttling Logic

**Canonical Rule:** Alerts throttled by time and price change

**Implementation:**
- ✅ `ALERT_COOLDOWN_MINUTES = 5` (from config)
- ✅ `ALERT_MIN_PRICE_CHANGE_PCT = 1.0` (from config)
- ✅ Uses `should_emit_signal()` from `signal_throttle.py`
- ✅ Tracks last alert time and price per symbol/side

✅ **Matches canonical rule** - Prevents alert spam

## Issues Found

### ⚠️ None - All Rules Correctly Implemented

No discrepancies found between canonical rules and implementation.

## Recommendations

1. ✅ **Continue monitoring** - Rules are correctly implemented
2. ✅ **Documentation is accurate** - Canonical rules match implementation
3. ✅ **Tests are passing** - Playwright tests validate frontend-backend consistency

## Conclusion

The business rule implementation is **100% compliant** with canonical rules. All critical logic matches the documented requirements:

- ✅ BUY/SELL decision logic
- ✅ MA checks respect config
- ✅ Index calculation matches decision flags
- ✅ Alerts separated from orders
- ✅ Portfolio risk only blocks orders, not alerts
- ✅ Throttling works correctly

**Status:** ✅ **VALIDATED AND COMPLIANT**















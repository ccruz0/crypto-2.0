# Telegram Origin Gatekeeper - Implementation Summary

**Date:** 2025-12-02  
**Status:** ✅ Complete (Updated to support TEST origin)

---

## Goal

Control which alerts are sent to production Telegram chat based on origin:
- **AWS origin**: Live runtime alerts → Sent to Telegram with `[AWS]` prefix
- **TEST origin**: Dashboard test alerts → Sent to Telegram with `[TEST]` prefix (visible in Monitoring)
- **LOCAL/DEBUG origin**: Development/debug alerts → Blocked from Telegram, logged only

---

## Key Implementation: Central Gatekeeper

### Location: `backend/app/services/telegram_notifier.py`

**Function:** `send_message(message: str, reply_markup: Optional[dict] = None, origin: Optional[str] = None)`

**Gatekeeper Logic:**
```python
# CENTRAL GATEKEEPER: Only AWS and TEST origins can send Telegram alerts
if origin is None:
    origin = get_runtime_origin()  # Fallback to runtime origin

origin_upper = origin.upper() if origin else "LOCAL"

# 1) Block all non-AWS, non-TEST origins from sending to Telegram
if origin_upper not in ("AWS", "TEST"):
    logger.info(
        f"[TG_LOCAL_DEBUG] Skipping Telegram send for non-AWS/non-TEST origin '{origin_upper}'. "
        f"Message would have been: {preview}"
    )
    # Register in dashboard for debugging, but mark as blocked
    add_telegram_message(f"[LOCAL DEBUG] {message}", symbol=symbol, blocked=True)
    return False  # DO NOT send to Telegram

# 2) For TEST origin: allow sending, but prefix with [TEST]
if origin_upper == "TEST":
    full_message = f"[TEST] {message}" if not message.startswith("[TEST]") else message
    # Send to Telegram and register in monitoring with blocked=False

# 3) For AWS origin: production alerts with [AWS] prefix
if origin_upper == "AWS":
    full_message = f"[AWS] {message}" if not message.startswith("[AWS]") else message
    # Send to Telegram and register in monitoring with blocked=False
```

---

## Origin Behavior Table

| origin | Prefix | Sends to TG | Shown in Monitoring | Notes |
|--------|--------|-------------|---------------------|-------|
| AWS | [AWS] | Yes | Yes (blocked=False) | Live runtime alerts |
| TEST | [TEST] | Yes | Yes (blocked=False) | Dashboard test alerts |
| LOCAL | — | No | Yes (blocked=True) | Debug only, logged but not sent |
| DEBUG | — | No | Yes (blocked=True) | Debug only, logged but not sent |

---

## Call Sites and Origins

### Production Alert Paths (origin = "AWS")

1. **SignalMonitorService - BUY alerts** (`signal_monitor.py`):
   - Line 1544: `send_buy_signal(..., origin=get_runtime_origin())`
   - Line 2176: `send_buy_signal(..., origin=get_runtime_origin())` (legacy path)
   - **Origin:** `get_runtime_origin()` → "AWS" in production

2. **SignalMonitorService - SELL alerts** (`signal_monitor.py`):
   - Line 2518: `send_sell_signal(..., origin=get_runtime_origin())`
   - **Origin:** `get_runtime_origin()` → "AWS" in production

### Test Paths (origin = "TEST")

3. **Test endpoint - simulate-alert** (`routes_test.py`):
   - Line 277: `send_buy_signal(..., origin="TEST")`
   - Line 469: `send_sell_signal(..., origin="TEST")`
   - **Origin:** Explicitly "TEST" to send test alerts to Telegram with [TEST] prefix
   - **Behavior:** Messages sent to Telegram and appear in Monitoring tab

### Debug Paths (origin = "LOCAL")

4. **Local development / debug scripts**:
   - Any calls with `origin="LOCAL"` or `origin="DEBUG"`
   - **Behavior:** Blocked from Telegram, logged with [TG_LOCAL_DEBUG], registered in Monitoring with blocked=True

### Other Direct send_message Calls

5. **Error notifications** (`signal_monitor.py`, `routes_test.py`):
   - Multiple calls to `send_message()` without explicit origin
   - **Behavior:** Defaults to `get_runtime_origin()` (which is "AWS" in production, "LOCAL" on Mac)
   - **Result:** Production errors sent to Telegram, local errors blocked ✅

---

## Updated Function Signatures

### `send_message()`
```python
def send_message(
    self, 
    message: str, 
    reply_markup: Optional[dict] = None, 
    origin: Optional[str] = None  # "AWS", "TEST", or "LOCAL"
) -> bool
```

### `send_buy_signal()`
```python
def send_buy_signal(
    self,
    symbol: str,
    price: float,
    reason: str,
    # ... other params ...
    origin: Optional[str] = None,  # "AWS", "TEST", or "LOCAL"
) -> bool
```

### `send_sell_signal()`
```python
def send_sell_signal(
    self,
    symbol: str,
    price: float,
    reason: str,
    # ... other params ...
    origin: Optional[str] = None,  # "AWS", "TEST", or "LOCAL"
) -> bool
```

---

## Test Coverage

**File:** `backend/tests/test_telegram_alerts_origin.py`

**Tests (10 total, all passing):**
1. ✅ `test_aws_origin_sends_telegram_message` - AWS origin sends to Telegram
2. ✅ `test_local_origin_does_not_send_telegram_message` - LOCAL origin blocks and logs
3. ✅ `test_send_buy_signal_with_aws_origin` - BUY signal with AWS sends
4. ✅ `test_send_buy_signal_with_local_origin` - BUY signal with LOCAL blocks
5. ✅ `test_send_sell_signal_with_aws_origin` - SELL signal with AWS sends
6. ✅ `test_send_sell_signal_with_local_origin` - SELL signal with LOCAL blocks
7. ✅ `test_default_origin_falls_back_to_runtime` - Default behavior uses runtime origin
8. ✅ `test_debug_origin_blocks_telegram` - DEBUG origin also blocks
9. ✅ `test_test_origin_sends_telegram_message` - TEST origin sends to Telegram with [TEST] prefix
10. ✅ `test_test_origin_recorded_in_monitoring` - TEST messages recorded in monitoring with blocked=False

**Run tests:**
```bash
cd /Users/carloscruz/automated-trading-platform/backend
poetry run pytest tests/test_telegram_alerts_origin.py -v
```

---

## Verification

### Expected Behavior in Production (AWS)

1. **SignalMonitorService detects BUY/SELL:**
   - Calls `send_buy_signal(..., origin=get_runtime_origin())`
   - `get_runtime_origin()` returns "AWS"
   - Gatekeeper allows send → Message sent to Telegram with `[AWS]` prefix
   - Log: `Telegram message sent successfully (origin=AWS)`

### Expected Behavior in Dashboard TEST

1. **Test endpoint simulates alert:**
   - Calls `send_buy_signal(..., origin="TEST")`
   - Gatekeeper allows send → Message sent to Telegram with `[TEST]` prefix
   - Log: `Telegram message sent successfully (origin=TEST)`
   - Dashboard shows: `[TEST] ...` with `blocked=False` in Monitoring tab

### Expected Behavior in Local/Debug

1. **Local development / debug scripts:**
   - Calls with `origin="LOCAL"` or `origin="DEBUG"`
   - Gatekeeper blocks send → Message NOT sent to Telegram
   - Log: `[TG_LOCAL_DEBUG] Skipping Telegram send for non-AWS/non-TEST origin 'LOCAL'. Message would have been: ...`
   - Dashboard shows: `[LOCAL DEBUG] ...` with `blocked=True`

---

## Files Modified

1. **`backend/app/services/telegram_notifier.py`**:
   - Extended gatekeeper to allow `origin="TEST"` in addition to `origin="AWS"`
   - Added [TEST] prefix logic for test alerts
   - Updated monitoring registration to keep prefixes for clarity

2. **`backend/app/services/signal_monitor.py`**:
   - Updated all `send_buy_signal()` calls to pass `origin=get_runtime_origin()`
   - Updated all `send_sell_signal()` calls to pass `origin=get_runtime_origin()`

3. **`backend/app/api/routes_test.py`**:
   - Updated test alert calls to pass `origin="TEST"` (changed from "LOCAL")

4. **`backend/tests/test_telegram_alerts_origin.py`**:
   - Added tests for TEST origin behavior
   - Updated existing tests to reflect new gatekeeper logic

5. **`docs/monitoring/business_rules_canonical.md`**:
   - Added section 4.4 documenting the origin gatekeeper

6. **`docs/WORKFLOWS_INDEX.md`**:
   - Updated section 2e documenting the gatekeeper behavior

---

## Summary

✅ **Central gatekeeper implemented** in `send_message()`  
✅ **AWS runtime** sends alerts to Telegram with [AWS] prefix  
✅ **Dashboard TEST button** sends alerts to Telegram with [TEST] prefix (visible in Monitoring)  
✅ **LOCAL/debug alerts** are blocked and logged for debugging  
✅ **10 tests** covering all scenarios (all passing)  
✅ **Documentation updated** in business rules and workflows index  

**Result:** 
- ✅ AWS runtime sends alerts to Telegram with [AWS] prefix
- ✅ Dashboard TEST button sends alerts to Telegram with [TEST] prefix (visible in Monitoring)
- ✅ All LOCAL/debug alerts are blocked and logged for debugging

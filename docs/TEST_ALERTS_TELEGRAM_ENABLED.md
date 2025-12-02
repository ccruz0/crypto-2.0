# TEST Alerts Now Send to Telegram

**Date:** 2025-12-02  
**Status:** ✅ Complete

---

## Summary

TEST alerts triggered from the AWS Dashboard (TEST button) now appear in Telegram and the Monitoring tab, clearly marked with `[TEST]` prefix. Local/debug alerts remain blocked.

---

## Changes Made

### 1. Extended Gatekeeper (`backend/app/services/telegram_notifier.py`)

**Before:**
- Only `origin="AWS"` could send to Telegram
- All other origins (including TEST) were blocked

**After:**
- `origin="AWS"` → Sends to Telegram with `[AWS]` prefix
- `origin="TEST"` → Sends to Telegram with `[TEST]` prefix
- `origin="LOCAL"` or `origin="DEBUG"` → Still blocked

**Key Code:**
```python
# 1) Block all non-AWS, non-TEST origins
if origin_upper not in ("AWS", "TEST"):
    # Block and log
    return False

# 2) For TEST origin: allow sending with [TEST] prefix
if origin_upper == "TEST":
    full_message = f"[TEST] {message}" if not message.startswith("[TEST]") else message
    # Send to Telegram and register in monitoring with blocked=False

# 3) For AWS origin: production alerts with [AWS] prefix
elif origin_upper == "AWS":
    full_message = f"[AWS] {message}" if not message.startswith("[AWS]") else message
    # Send to Telegram and register in monitoring with blocked=False
```

### 2. Updated Test Endpoints (`backend/app/api/routes_test.py`)

**Before:**
```python
origin="LOCAL",  # Test alerts should not send to production Telegram
```

**After:**
```python
origin="TEST",  # Test alerts from dashboard should send to Telegram with [TEST] prefix
```

**Changed in:**
- BUY test endpoint (line 277)
- SELL test endpoint (line 469)

### 3. Updated Tests (`backend/tests/test_telegram_alerts_origin.py`)

**Added:**
- `test_test_origin_sends_telegram_message` - Verifies TEST origin sends with [TEST] prefix
- `test_test_origin_recorded_in_monitoring` - Verifies TEST messages appear in Monitoring

**Updated:**
- Existing tests adjusted to reflect new gatekeeper logic (10 tests total, all passing)

### 4. Updated Documentation

- `docs/monitoring/TELEGRAM_ORIGIN_GATEKEEPER_SUMMARY.md` - Complete rewrite with TEST origin support
- `docs/WORKFLOWS_INDEX.md` - Updated section 2e to mention TEST alerts

---

## Behavior Table

| origin | Prefix | Sends to TG | Shown in Monitoring | Notes |
|--------|--------|-------------|---------------------|-------|
| AWS | [AWS] | Yes | Yes (blocked=False) | Live runtime alerts |
| TEST | [TEST] | Yes | Yes (blocked=False) | Dashboard test alerts |
| LOCAL | — | No | Yes (blocked=True) | Debug only, logged but not sent |
| DEBUG | — | No | Yes (blocked=True) | Debug only, logged but not sent |

---

## Verification Steps

### 1. Test SELL Alert

1. Open `https://dashboard.hilovivo.com`
2. Go to Watchlist tab
3. Find a symbol (e.g., ALGO_USDT)
4. Set:
   - BUY alerts: OFF
   - SELL alerts: ON
5. Click TEST button
6. Confirm modal shows "¿Simular alerta SELL para ALGO_USDT?"
7. Accept the test

**Expected Results:**
- ✅ Telegram message received starting with `[TEST] 🟥 SELL SIGNAL DETECTED`
- ✅ Monitoring → Telegram Messages shows entry with `[TEST]` prefix
- ✅ Entry is NOT marked as blocked

### 2. Test BUY Alert

1. Same symbol, set:
   - BUY alerts: ON
   - SELL alerts: OFF
2. Click TEST button
3. Confirm modal shows "¿Simular alerta BUY para ALGO_USDT?"
4. Accept the test

**Expected Results:**
- ✅ Telegram message received starting with `[TEST] 🟢 BUY SIGNAL DETECTED`
- ✅ Monitoring → Telegram Messages shows entry with `[TEST]` prefix
- ✅ Entry is NOT marked as blocked

---

## Files Modified

1. `backend/app/services/telegram_notifier.py` - Extended gatekeeper
2. `backend/app/api/routes_test.py` - Changed origin from "LOCAL" to "TEST"
3. `backend/tests/test_telegram_alerts_origin.py` - Added TEST origin tests
4. `docs/monitoring/TELEGRAM_ORIGIN_GATEKEEPER_SUMMARY.md` - Complete update
5. `docs/WORKFLOWS_INDEX.md` - Updated section 2e

---

## Deployment

**Deployed to AWS:** ✅ Complete
- Backend rebuilt and restarted
- Health check: `{"status":"ok"}`
- Ready for testing

---

## Next Steps

1. Test SELL alert from dashboard (BUY=OFF, SELL=ON)
2. Test BUY alert from dashboard (BUY=ON, SELL=OFF)
3. Verify messages appear in Telegram with [TEST] prefix
4. Verify messages appear in Monitoring tab with [TEST] prefix
5. Confirm LOCAL alerts still blocked (if testing locally)


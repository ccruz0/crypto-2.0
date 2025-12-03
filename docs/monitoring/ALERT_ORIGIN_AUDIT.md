# Alert Origin Audit Workflow

**Purpose:** Detect any place where AWS notifications (Telegram or others) might be hardcoded to be blocked, mis-routed, or mis-labeled.

**Last Updated:** 2025-01-XX

---

## Overview

This workflow provides a repeatable process to audit the codebase for any logic that might prevent AWS notifications from being sent. The audit checks for:

1. Hardcoded origin blocking (e.g., `if origin == "AWS": return False`)
2. Environment-based disable flags that might affect AWS
3. Mis-routed origins (e.g., forcing `origin="LOCAL"` in AWS runtime)
4. Missing origin parameters in alert functions

---

## Quick Start

Run the automated audit script:

```bash
cd /Users/carloscruz/automated-trading-platform
bash scripts/audit_alert_origins.sh
```

The script will:
- Search for all origin-related patterns
- Check for suspicious blocking logic
- Verify docker-compose configuration
- Report any issues found

---

## How Alert Origins Work

### Origin Types

The system uses three origin types:

1. **`AWS`** - Production runtime on AWS
   - Sends alerts to Telegram with `[AWS]` prefix
   - Only origin that sends production alerts
   - Set via `RUNTIME_ORIGIN=AWS` in docker-compose

2. **`TEST`** - Test alerts from dashboard
   - Sends alerts to Telegram with `[TEST]` prefix
   - Used by `/api/test/simulate-alert` endpoint
   - Visible in Monitoring tab

3. **`LOCAL`** - Local development runtime
   - **BLOCKED** from sending to Telegram
   - Logs `[TG_LOCAL_DEBUG]` instead
   - Default when `RUNTIME_ORIGIN` is not set

### Origin Flow

```
signal_monitor.py
  ↓
get_runtime_origin() → "AWS" (if RUNTIME_ORIGIN=AWS)
  ↓
send_buy_signal(..., origin=origin)
  ↓
telegram_notifier.send_message(..., origin=origin)
  ↓
Gatekeeper: if origin_upper not in ("AWS", "TEST"): return False
  ↓
Telegram API (if origin == "AWS" or "TEST")
```

---

## Audit Script Commands

The audit script (`scripts/audit_alert_origins.sh`) performs the following searches:

### 1. RUNTIME_ORIGIN References
```bash
rg "RUNTIME_ORIGIN" .
```
**What to look for:**
- Should be set to `AWS` in `docker-compose.yml` for `backend-aws` service
- Should default to `LOCAL` in `config.py` for safety

### 2. Origin Assignments
```bash
rg "origin\s*=" backend -n
```
**What to look for:**
- `origin = get_runtime_origin()` - ✅ Correct
- `origin = "LOCAL"` - ⚠️ Suspicious if in production code
- `origin = "AWS"` - ⚠️ Suspicious (should use `get_runtime_origin()`)

### 3. AWS References
```bash
rg "AWS" backend -n
```
**What to look for:**
- `origin_upper == "AWS"` - ✅ Allowed in gatekeeper
- `if origin == "AWS": return False` - ❌ **DANGEROUS** - blocks AWS alerts
- `if get_runtime_origin() == "AWS": return` - ❌ **DANGEROUS** - blocks AWS alerts

### 4. [AWS] Prefix Patterns
```bash
rg "\[AWS\]" backend -n
```
**What to look for:**
- Should only appear in `telegram_notifier.py` for prefixing messages
- Should NOT be used to block alerts

### 5. LOCAL References
```bash
rg "LOCAL" backend -n
```
**What to look for:**
- `origin_upper not in ("AWS", "TEST")` - ✅ Correct gatekeeper logic
- `origin = "LOCAL"` - ⚠️ Check if this forces LOCAL in AWS runtime

### 6. TG_LOCAL_DEBUG Patterns
```bash
rg "TG_LOCAL_DEBUG" backend -n
```
**What to look for:**
- Should only appear in logging when LOCAL origin is blocked
- Should NOT appear for AWS origin

### 7. Disable Flags
```bash
rg "DISABLE_ALERT\|DISABLE_TELEGRAM\|ENABLE_TELEGRAM\|TELEGRAM_DISABLED" backend -n
```
**What to look for:**
- `DISABLE_ALERTS_IN_AWS` - ❌ **DANGEROUS** - would block AWS alerts
- `DISABLE_TELEGRAM_IN_AWS` - ❌ **DANGEROUS** - would block AWS alerts
- `RUN_TELEGRAM=false` in AWS compose - ❌ **DANGEROUS** - would disable Telegram

### 8. send_message/send_buy_signal/send_sell_signal Calls
```bash
rg "send_message\|send_buy_signal\|send_sell_signal" backend -n
```
**What to look for:**
- All calls should pass `origin` parameter
- `send_buy_signal(..., origin=origin)` - ✅ Correct
- `send_buy_signal(...)` without origin - ⚠️ May default incorrectly

---

## What to Look For: Dangerous Patterns

### ❌ Pattern 1: Blocking AWS Origin

```python
# DANGEROUS - Blocks AWS alerts
if origin_upper == "AWS":
    return False

# DANGEROUS - Blocks AWS alerts
if get_runtime_origin() == "AWS":
    return False
```

**Fix:** Remove blocking logic or ensure it only blocks LOCAL/DEBUG, not AWS.

### ❌ Pattern 2: Environment-Based Blocking

```python
# DANGEROUS - May block AWS if environment is misconfigured
if settings.environment == "prod":
    return False  # This would block AWS!

# DANGEROUS - Disables Telegram in production
if is_aws_runtime() and DISABLE_ALERTS_IN_AWS:
    return False
```

**Fix:** Ensure AWS is always allowed, regardless of environment flags.

### ❌ Pattern 3: Forcing LOCAL Origin in AWS

```python
# DANGEROUS - Forces LOCAL even in AWS runtime
origin = "LOCAL"  # This would block all alerts in AWS!

# DANGEROUS - Overrides runtime origin
if some_condition:
    origin = "LOCAL"  # Blocks alerts even in AWS
```

**Fix:** Always use `get_runtime_origin()` or pass origin explicitly from caller.

### ❌ Pattern 4: Missing Origin Parameter

```python
# DANGEROUS - May default to LOCAL in AWS
telegram_notifier.send_buy_signal(symbol, price, reason)  # Missing origin!

# DANGEROUS - May use wrong origin
send_message(message)  # Should pass origin=origin
```

**Fix:** Always pass `origin` parameter explicitly.

### ❌ Pattern 5: Docker Compose Misconfiguration

```yaml
# DANGEROUS - Disables Telegram in AWS
backend-aws:
  environment:
    - RUN_TELEGRAM=false  # ❌ Would disable all Telegram alerts
    - RUNTIME_ORIGIN=LOCAL  # ❌ Would block all alerts

# DANGEROUS - Missing RUNTIME_ORIGIN
backend-aws:
  environment:
    # Missing RUNTIME_ORIGIN - defaults to LOCAL, blocks alerts!
```

**Fix:** Ensure `RUNTIME_ORIGIN=AWS` and `RUN_TELEGRAM=true` in AWS compose.

---

## Key Files to Audit

### 1. `backend/app/services/telegram_notifier.py`

**Gatekeeper Logic (lines 171-215):**
```python
# CENTRAL GATEKEEPER: Only AWS and TEST origins can send Telegram alerts
if origin_upper not in ("AWS", "TEST"):
    # Block LOCAL/DEBUG origins
    logger.info(f"[TG_LOCAL_DEBUG] Skipping Telegram send...")
    return False

# AWS origin: production alerts with [AWS] prefix
elif origin_upper == "AWS":
    full_message = f"[AWS] {message}"
    # Send to Telegram
```

**What to verify:**
- ✅ Gatekeeper allows `AWS` and `TEST`
- ✅ Gatekeeper blocks `LOCAL` and other origins
- ✅ No additional blocking logic for AWS

### 2. `backend/app/services/signal_monitor.py`

**Origin Usage (lines 1177, 1544, 2176, 2519):**
```python
origin = get_runtime_origin()
result = telegram_notifier.send_buy_signal(
    ...,
    origin=origin,  # ✅ Passes runtime origin
)
```

**What to verify:**
- ✅ Uses `get_runtime_origin()` to get origin
- ✅ Passes `origin` to `send_buy_signal` and `send_sell_signal`
- ✅ No logic that forces `origin="LOCAL"` in AWS runtime

### 3. `backend/app/api/routes_test.py`

**Test Alerts (lines 287, 484):**
```python
telegram_notifier.send_buy_signal(
    ...,
    origin="TEST",  # ✅ Test alerts use TEST origin
)
```

**What to verify:**
- ✅ Test endpoints use `origin="TEST"`
- ✅ No logic that blocks when `get_runtime_origin() == "AWS"`

### 4. `docker-compose.yml`

**AWS Backend Configuration (lines 143-206):**
```yaml
backend-aws:
  environment:
    - ENVIRONMENT=aws
    - APP_ENV=aws
    - RUN_TELEGRAM=${RUN_TELEGRAM:-true}  # ✅ Should be true
    - RUNTIME_ORIGIN=AWS  # ✅ Must be AWS
```

**What to verify:**
- ✅ `RUNTIME_ORIGIN=AWS` is set
- ✅ `RUN_TELEGRAM=true` (or from env, defaults to true)
- ✅ No `DISABLE_*` flags that would block alerts

### 5. `backend/app/core/runtime.py`

**Runtime Origin Detection:**
```python
def get_runtime_origin() -> str:
    runtime_origin = (settings.RUNTIME_ORIGIN or "").strip().upper()
    if runtime_origin == "AWS":
        return "AWS"
    return "LOCAL"  # Default for safety
```

**What to verify:**
- ✅ Returns `"AWS"` when `RUNTIME_ORIGIN=AWS`
- ✅ Defaults to `"LOCAL"` for safety
- ✅ No logic that blocks AWS

---

## Expected Behavior

### ✅ Correct Behavior

1. **AWS Runtime (`RUNTIME_ORIGIN=AWS`):**
   - `get_runtime_origin()` returns `"AWS"`
   - `signal_monitor.py` passes `origin="AWS"` to alert functions
   - `telegram_notifier.send_message()` allows AWS origin
   - Alerts are sent to Telegram with `[AWS]` prefix

2. **TEST Alerts (`origin="TEST"`):**
   - Dashboard test button uses `origin="TEST"`
   - `telegram_notifier.send_message()` allows TEST origin
   - Alerts are sent to Telegram with `[TEST]` prefix
   - Visible in Monitoring tab

3. **LOCAL Runtime (`RUNTIME_ORIGIN=LOCAL` or unset):**
   - `get_runtime_origin()` returns `"LOCAL"`
   - `telegram_notifier.send_message()` blocks LOCAL origin
   - Logs `[TG_LOCAL_DEBUG]` instead of sending
   - Alerts are NOT sent to Telegram

### ❌ Incorrect Behavior (Issues to Fix)

1. **AWS alerts blocked:**
   - `origin="AWS"` but alerts not sent
   - `[TG_LOCAL_DEBUG]` appears for AWS origin
   - No `[AWS]` messages in Telegram

2. **Origin forced to LOCAL:**
   - AWS runtime but `origin="LOCAL"` in logs
   - `get_runtime_origin()` returns `"AWS"` but alerts use `"LOCAL"`

3. **Missing origin parameter:**
   - `send_buy_signal()` called without `origin` parameter
   - Defaults to runtime origin, but may be incorrect

---

## Audit Results (2025-01-XX)

### ✅ No Issues Found

The audit script was run and found **no suspicious blocking patterns**. Key findings:

1. **telegram_notifier.py gatekeeper:**
   - ✅ Correctly allows `AWS` and `TEST` origins
   - ✅ Blocks `LOCAL` and other origins (as intended)
   - ✅ No additional blocking logic for AWS

2. **signal_monitor.py:**
   - ✅ Uses `get_runtime_origin()` to get origin
   - ✅ Passes `origin` parameter to `send_buy_signal()` and `send_sell_signal()`
   - ✅ No logic that forces `origin="LOCAL"` in AWS runtime

3. **routes_test.py:**
   - ✅ Test endpoints use `origin="TEST"` for test alerts
   - ✅ No logic that blocks when `get_runtime_origin() == "AWS"`

4. **docker-compose.yml:**
   - ✅ `backend-aws` service sets `RUNTIME_ORIGIN=AWS`
   - ✅ `backend-aws` service sets `RUN_TELEGRAM=${RUN_TELEGRAM:-true}` (defaults to true)
   - ✅ No `DISABLE_*` flags that would block AWS alerts

5. **No dangerous patterns found:**
   - ✅ No `if origin == "AWS": return False` patterns
   - ✅ No `if get_runtime_origin() == "AWS": return` patterns
   - ✅ No forced `origin="LOCAL"` assignments in production code
   - ✅ No environment flags that disable AWS alerts

**Conclusion:** AWS alerts should be working correctly. The gatekeeper logic properly allows AWS and TEST origins while blocking LOCAL/DEBUG origins.

---

## Fixes Applied (If Any)

### Before/After Examples

If issues are found and fixed in future audits, document them here:

#### Example Fix 1: Removed AWS Blocking Logic

**Before:**
```python
# backend/app/services/telegram_notifier.py
if origin_upper == "AWS" and DISABLE_ALERTS_IN_AWS:
    return False  # ❌ Blocks AWS alerts
```

**After:**
```python
# backend/app/services/telegram_notifier.py
# Removed blocking logic - AWS should always be allowed
if origin_upper not in ("AWS", "TEST"):
    return False  # ✅ Only blocks non-AWS/non-TEST
```

#### Example Fix 2: Fixed Missing Origin Parameter

**Before:**
```python
# backend/app/services/signal_monitor.py
telegram_notifier.send_buy_signal(
    symbol=symbol,
    price=current_price,
    reason=reason_text,
    # ❌ Missing origin parameter
)
```

**After:**
```python
# backend/app/services/signal_monitor.py
origin = get_runtime_origin()
telegram_notifier.send_buy_signal(
    symbol=symbol,
    price=current_price,
    reason=reason_text,
    origin=origin,  # ✅ Passes runtime origin
)
```

---

## Running the Audit

### Manual Audit Steps

1. **Set context:**
   ```bash
   cd /Users/carloscruz/automated-trading-platform
   ```

2. **Run automated script:**
   ```bash
   bash scripts/audit_alert_origins.sh
   ```

3. **Review output:**
   - ✅ No suspicious patterns = AWS alerts should work
   - ⚠️ Suspicious patterns found = Review flagged files

4. **Manual verification (if needed):**
   - Check `docker-compose.yml` for `RUNTIME_ORIGIN=AWS`
   - Verify `telegram_notifier.py` gatekeeper logic
   - Check `signal_monitor.py` origin usage
   - Review `routes_test.py` for test origin handling

### Automated Audit Script

The script (`scripts/audit_alert_origins.sh`) performs:
- ✅ Searches for all origin-related patterns
- ✅ Checks for suspicious blocking logic
- ✅ Verifies docker-compose configuration
- ✅ Reports summary of findings

**Exit codes:**
- `0` = No suspicious patterns found
- `1` = Suspicious patterns found (review required)

---

## Related Documentation

- **Telegram Origin Gatekeeper:** `docs/monitoring/TELEGRAM_ORIGIN_GATEKEEPER_SUMMARY.md`
- **Test Alerts Status:** `docs/monitoring/TEST_ALERTS_END_TO_END_STATUS.md`
- **Runtime Health Check:** `docs/FULL_RUNTIME_HEALTH_AUDIT.md`
- **Business Rules:** `docs/monitoring/business_rules_canonical.md`

---

## Summary

This audit workflow ensures that:

1. ✅ AWS runtime (`RUNTIME_ORIGIN=AWS`) can send alerts
2. ✅ TEST alerts (`origin="TEST"`) can send alerts
3. ✅ LOCAL runtime (`RUNTIME_ORIGIN=LOCAL`) is blocked from sending
4. ✅ No hardcoded blocking of AWS alerts
5. ✅ No environment flags that disable AWS alerts
6. ✅ Origin is correctly passed through the alert chain

**Key Principle:** AWS alerts should **ALWAYS** be allowed by default. Any blocking logic should only affect LOCAL/DEBUG origins, never AWS.

---

## E2E Telegram + Monitoring Test

### Overview

The E2E (End-to-End) test provides a minimal, isolated test workflow to debug why TEST alerts might not reach Telegram or the Monitoring tab. It bypasses all strategy logic and signal processing, sending a simple test message directly through the alert pipeline.

### Endpoint

**POST** `/api/test/e2e-alert`

**Behavior:**
1. Detects current runtime origin via `get_runtime_origin()`
2. Builds a simple test message with origin and environment info
3. Calls `telegram_notifier.send_message()` directly
4. Registers the message in Monitoring if successful
5. Returns detailed status with origin, success flags, and configuration

**Response:**
```json
{
  "ok": true,
  "origin": "AWS",
  "success": true,
  "monitoring_saved": true,
  "telegram_enabled": true,
  "environment": "aws",
  "app_env": "aws",
  "run_telegram": "true",
  "message": "E2E test completed - check logs for [E2E_TEST_*] markers"
}
```

### How to Run

**From your Mac:**

```bash
cd /Users/carloscruz/automated-trading-platform
bash scripts/e2e_test_alert_remote.sh
```

The script will:
1. Trigger the E2E test endpoint on AWS backend
2. Display the API response
3. Show the last 300 log lines filtered for `E2E_TEST` markers

### What Logs to Look For

The E2E test adds comprehensive logging at every step. Look for these markers in the logs:

#### 1. Endpoint Entry
```
[E2E_TEST] Incoming request, origin=AWS
[E2E_TEST] Built message, length=123, origin=AWS
[E2E_TEST] Calling telegram_notifier.send_message(origin=AWS)
```

#### 2. Gatekeeper Logs
```
[E2E_TEST_GATEKEEPER_IN] message_len=123, origin=AWS
[E2E_TEST_GATEKEEPER_ORIGIN] origin_upper=AWS
```

**If blocked:**
```
[E2E_TEST_GATEKEEPER_BLOCK] origin_upper=LOCAL, message_preview=...
```

**If Telegram disabled:**
```
[E2E_TEST_CONFIG] Telegram sending disabled by configuration (RUN_TELEGRAM or similar)
[E2E_TEST_CONFIG] telegram_notifier.enabled=False
[E2E_TEST_CONFIG] RUN_TELEGRAM env=false
```

#### 3. Telegram API Logs
```
[E2E_TEST_SENDING_TELEGRAM] origin_upper=AWS, prefix=[AWS], message_preview=...
[E2E_TEST_TELEGRAM_OK] origin_upper=AWS, message_id=12345
```

**If error:**
```
[E2E_TEST_TELEGRAM_ERROR] origin_upper=AWS, error=...
```

#### 4. Monitoring Registration
```
[E2E_TEST] Registering in Monitoring, symbol=E2E_TEST, blocked=False
[E2E_TEST_MONITORING_SAVE] message_preview=..., symbol=E2E_TEST, blocked=False
[E2E_TEST] Monitoring registration: success=True
```

#### 5. Final Result
```
[E2E_TEST] Telegram send result: success=True
```

### Expected Flow

**Successful E2E Test (AWS origin):**
1. ✅ `[E2E_TEST] Incoming request, origin=AWS`
2. ✅ `[E2E_TEST_GATEKEEPER_IN]` → `[E2E_TEST_GATEKEEPER_ORIGIN] origin_upper=AWS`
3. ✅ `[E2E_TEST_SENDING_TELEGRAM]` → `[E2E_TEST_TELEGRAM_OK]`
4. ✅ `[E2E_TEST_MONITORING_SAVE]` → `[E2E_TEST] Monitoring registration: success=True`
5. ✅ Message appears in Telegram with `[AWS]` prefix
6. ✅ Message appears in Monitoring tab with `symbol=E2E_TEST`

**Failed E2E Test (common issues):**

**Issue 1: Telegram Disabled**
- Look for: `[E2E_TEST_CONFIG] Telegram sending disabled`
- Check: `RUN_TELEGRAM` env var, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`

**Issue 2: Origin Blocked**
- Look for: `[E2E_TEST_GATEKEEPER_BLOCK]`
- Check: Origin is not `AWS` or `TEST` (should be `AWS` on AWS backend)

**Issue 3: Telegram API Error**
- Look for: `[E2E_TEST_TELEGRAM_ERROR]`
- Check: Network connectivity, Telegram API status, bot token validity

**Issue 4: Monitoring Not Saved**
- Look for: `[E2E_TEST] Monitoring registration: success=False`
- Check: Database connection, `add_telegram_message()` function

### Debugging Tips

1. **Check origin first:** If `origin` is not `AWS` on AWS backend, check `RUNTIME_ORIGIN` env var
2. **Check Telegram config:** Look for `[E2E_TEST_CONFIG]` logs to see what's disabled
3. **Check gatekeeper:** Look for `[E2E_TEST_GATEKEEPER_*]` logs to see if message is blocked
4. **Check API call:** Look for `[E2E_TEST_SENDING_TELEGRAM]` and `[E2E_TEST_TELEGRAM_OK/ERROR]`
5. **Check Monitoring:** Look for `[E2E_TEST_MONITORING_SAVE]` to see if message is registered

### Integration with Alert Origin Audit

This E2E test complements the Alert Origin Audit by:
- Testing the actual alert flow end-to-end
- Providing detailed logs at every step
- Isolating issues to specific components (gatekeeper, Telegram API, Monitoring)
- Verifying that TEST alerts work correctly when origin is explicitly set

**Use this test when:**
- TEST alerts from dashboard don't reach Telegram
- TEST alerts don't appear in Monitoring tab
- You need to verify the complete alert pipeline
- You want to debug a specific failure point


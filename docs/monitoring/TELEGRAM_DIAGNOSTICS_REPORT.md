# Telegram Diagnostics Report

## Overview

This report documents the diagnostic instrumentation added to identify why some Telegram alerts don't reach Telegram while the daily sales report works reliably.

## Problem Statement

- **Working:** Daily sales report always reaches Telegram
- **Not Working:** Many signal alerts, monitoring alerts, and other alert types don't reach Telegram
- **Unified Path:** All alerts use the same `telegram_notifier.send_message()` path

## Root Cause Hypothesis

Since all alerts use the same code path, the issue is likely:

1. **Origin Detection:** Different execution contexts may detect different origins
2. **Gatekeeper Filtering:** Gatekeeper conditions may block some alerts
3. **Environment Variables:** Some execution contexts may be missing required env vars
4. **Silent Failures:** Exceptions may be caught and swallowed without proper logging
5. **Execution Context:** Signal monitor may run in different worker/process with different env

## Diagnostic Instrumentation Added

### 1. Comprehensive Logging in `send_message()`

Added four diagnostic log tags to `telegram_notifier.py:send_message()`:

#### [TELEGRAM_INVOKE]
Logs at entry point with:
- Timestamp
- Origin parameter value
- Message length
- Symbol extracted from message
- Caller function path (file:line in function)
- Environment variables:
  - `RUNTIME_ORIGIN`
  - `AWS_EXECUTION_ENV` / `AWS_EXECUTION`
  - `RUN_TELEGRAM`
  - `TELEGRAM_BOT_TOKEN` (presence only)
  - `TELEGRAM_CHAT_ID` (presence only)

#### [TELEGRAM_GATEKEEPER]
Logs all gatekeeper conditions:
- `origin_upper` value
- `origin_in_whitelist` (True if "AWS" or "TEST")
- `self.enabled` (Telegram enabled flag)
- `bot_token_present` (Boolean)
- `chat_id_present` (Boolean)
- **RESULT**: "ALLOW" or "BLOCK"

#### [TELEGRAM_REQUEST]
Logs before sending HTTP request:
- URL (with token masked)
- Payload keys (not values for security)
- Timeout seconds
- Message length

#### [TELEGRAM_RESPONSE]
Logs HTTP response:
- HTTP status code
- **RESULT**: "SUCCESS" or "FAILURE"
- Response text (for non-200 status)
- Message ID (for successful sends)

### 2. Debug Test Function

Added `telegram_notifier.debug_test_alert()` to test alert sending:
- Accepts `alert_type`, `symbol`, and `origin` parameters
- Sends test message with explicit parameters
- Can be called from any execution context to test that context

### 3. Diagnostic Script

Created `scripts/diagnose_telegram_paths.py`:
- Tests all alert paths:
  1. Daily sales report style
  2. BUY signal alert
  3. SELL signal alert
  4. Order created alert
  5. Monitoring alert (direct send_message)
  6. Debug test alert
  7. Debug test alert with explicit AWS origin
  8. Simplified test alert
- Prints environment variables
- Reports SUCCESS/FAILURE for each test
- Guides troubleshooting based on results

## Comparison: Daily Report vs Other Alerts

### Working Path: Daily Sales Report

**Call Chain:**
```
scheduler.py:132 → daily_summary.py:300 → telegram_notifier.send_message(message)
```

**Characteristics:**
- Execution Context: Scheduled task → async thread pool → sync worker
- Origin: `None` → defaults to `get_runtime_origin()` → "AWS"
- Environment: Full AWS environment with all env vars
- Success Rate: 100% ✅

### Other Alert Paths

**Call Chain (BUY Signal Example):**
```
signal_monitor.py:1225 → telegram_notifier.send_buy_signal() → send_message()
```

**Characteristics:**
- Execution Context: Signal monitor loop (may be different worker)
- Origin: `None` → defaults to `get_runtime_origin()` → "AWS" (should be)
- Environment: Should be same, but **verify**
- Success Rate: Inconsistent ❌

## Key Differences to Investigate

1. **Execution Context**
   - Daily report: Scheduler → thread pool
   - Signal alerts: Signal monitor service loop
   - **Action:** Verify env vars are available in signal monitor context

2. **Origin Detection**
   - Both use `get_runtime_origin()` when `origin=None`
   - **Action:** Compare `RUNTIME_ORIGIN` env var in both contexts

3. **Gatekeeper Checks**
   - Both should pass same checks
   - **Action:** Compare `[TELEGRAM_GATEKEEPER]` logs between working/non-working

4. **Exception Handling**
   - Signal monitor has try/except blocks that log warnings
   - **Action:** Verify exceptions aren't being swallowed silently

## Environment Variables (AWS)

### Required Variables

From `docker-compose.yml:backend-aws`:

```yaml
environment:
  - ENVIRONMENT=aws
  - APP_ENV=aws
  - RUN_TELEGRAM=${RUN_TELEGRAM:-true}
  - RUNTIME_ORIGIN=AWS
  # TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID loaded from .env.aws
```

### Verification Needed

Check that all of these are available in signal monitor execution context:
- ✅ `RUNTIME_ORIGIN=AWS`
- ✅ `RUN_TELEGRAM=true`
- ✅ `TELEGRAM_BOT_TOKEN` (from .env.aws)
- ✅ `TELEGRAM_CHAT_ID` (from .env.aws)

## Testing Instructions

### Step 1: Run Diagnostic Script in AWS

```bash
ssh hilovivo-aws 'cd /home/ubuntu/automated-trading-platform && \
docker compose --profile aws exec backend-aws python scripts/diagnose_telegram_paths.py'
```

**Expected Output:**
- Environment variables listed
- Each test shows SUCCESS or FAILURE
- Diagnostic logs for each test

### Step 2: Analyze Logs

Search for diagnostic tags in logs:

```bash
ssh hilovivo-aws 'cd /home/ubuntu/automated-trading-platform && \
docker compose --profile aws logs backend-aws | grep -E "\[TELEGRAM_INVOKE\]|\[TELEGRAM_GATEKEEPER\]|\[TELEGRAM_REQUEST\]|\[TELEGRAM_RESPONSE\]" | tail -100'
```

### Step 3: Compare Working vs Non-Working

Compare logs for:
1. Daily sales report (working)
2. Signal alert (not working)

Look for differences in:
- `[TELEGRAM_INVOKE]` environment variables
- `[TELEGRAM_GATEKEEPER]` RESULT
- `[TELEGRAM_RESPONSE]` status

### Step 4: Identify Root Cause

Based on diagnostic output, identify:
- Which gatekeeper condition fails
- Which environment variable is missing
- Which execution context differs

## Potential Fixes

### Fix 1: Ensure Origin is Explicit

If origin detection is inconsistent, explicitly pass `origin="AWS"` in all alert calls:

```python
# In signal_monitor.py
telegram_notifier.send_buy_signal(..., origin="AWS")
```

### Fix 2: Ensure Environment Variables

If env vars are missing in signal monitor context:
- Verify docker-compose.yml passes all required vars
- Check that signal monitor service inherits env vars
- Add explicit env var checks in signal monitor startup

### Fix 3: Fix Silent Failures

If exceptions are being swallowed:
- Review exception handlers in signal_monitor.py
- Ensure all exceptions are logged with full context
- Add re-raise for critical failures

### Fix 4: Verify Execution Context

If execution contexts differ:
- Ensure signal monitor runs in same container as scheduler
- Verify all workers have same environment
- Check for environment isolation issues

## Next Steps

1. **Run Diagnostic Script:** Execute `diagnose_telegram_paths.py` in AWS
2. **Collect Logs:** Gather diagnostic logs for working and non-working alerts
3. **Compare Results:** Identify differences between working and non-working paths
4. **Apply Fixes:** Based on diagnostics, apply minimal fixes
5. **Verify:** Test all alert types to confirm they reach Telegram

## Files Modified

1. `backend/app/services/telegram_notifier.py`
   - Added `[TELEGRAM_INVOKE]` logging
   - Added `[TELEGRAM_GATEKEEPER]` logging
   - Added `[TELEGRAM_REQUEST]` logging
   - Added `[TELEGRAM_RESPONSE]` logging
   - Added `debug_test_alert()` function

2. `scripts/diagnose_telegram_paths.py`
   - New diagnostic script to test all alert paths

3. `docs/monitoring/TELEGRAM_CALL_PATH_COMPARISON.md`
   - Comparison document between daily report and other alerts

4. `docs/monitoring/TELEGRAM_DIAGNOSTICS_REPORT.md`
   - This report

## Summary

All diagnostic instrumentation is now in place. The next step is to:

1. Run the diagnostic script in AWS
2. Compare the logs between working (daily report) and non-working (signal alerts) paths
3. Identify the specific difference causing alerts to fail
4. Apply targeted fix based on diagnostics

The diagnostic logs will reveal exactly where and why alerts are being blocked or failing.

# Telegram Call Path Comparison

## Overview

This document compares the call paths between the **working daily sales report** and other alert types to identify why some alerts don't reach Telegram.

## Working Path: Daily Sales Report

### Call Chain

```
scheduler.py:132 (check_sell_orders_report_sync)
    ↓
daily_summary.py:300 (send_sell_orders_report)
    ↓
self.telegram.send_message(message)
    ↓
telegram_notifier.send_message(message, reply_markup=None, origin=None)
    ↓
Origin Detection: origin = get_runtime_origin()  # Returns "AWS" in AWS
    ↓
Gatekeeper: origin_upper == "AWS" → ALLOW
    ↓
Add [AWS] prefix
    ↓
Telegram API: requests.post("https://api.telegram.org/bot{token}/sendMessage")
    ↓
SUCCESS: Message sent to Telegram
```

### Key Characteristics

- **File:** `backend/app/services/daily_summary.py:300`
- **Function:** `send_sell_orders_report()`
- **Call:** `self.telegram.send_message(message)`
- **Origin Parameter:** `None` (defaults to `get_runtime_origin()`)
- **Message Format:** Plain text with HTML formatting
- **Parse Mode:** HTML (default in send_message)
- **Execution Context:** Scheduled task (scheduler.py) → async thread pool → sync worker
- **Environment:** Full AWS environment with all env vars

## Other Alert Paths

### 1. BUY Signal Alert

**Call Chain:**
```
signal_monitor.py:1225 (process_buy_signal)
    ↓
telegram_notifier.send_buy_signal(...)
    ↓
telegram_notifier.py:812 (send_buy_signal)
    ↓
origin = get_runtime_origin() if origin is None
    ↓
telegram_notifier.send_message(message, origin=origin)
    ↓
[Same path as daily report from here]
```

**Key Characteristics:**
- **File:** `backend/app/services/signal_monitor.py:1225`
- **Function:** Calls `telegram_notifier.send_buy_signal()`
- **Origin Parameter:** `None` (defaults in send_buy_signal to `get_runtime_origin()`)
- **Message Format:** Formatted HTML with emojis
- **Parse Mode:** HTML (default)
- **Execution Context:** Signal monitor loop (may run in different worker)
- **Environment:** Should be same as daily report, but verify

**Differences:**
- ✅ Uses same `send_message()` path
- ✅ Origin defaults to `get_runtime_origin()` (same as daily report)
- ⚠️ **Potential Issue:** Execution context may be different worker/process

### 2. SELL Signal Alert

**Call Chain:**
```
signal_monitor.py:2088 (process_sell_signal)
    ↓
telegram_notifier.send_sell_signal(...)
    ↓
telegram_notifier.py:897 (send_sell_signal)
    ↓
origin = get_runtime_origin() if origin is None
    ↓
telegram_notifier.send_message(message, origin=origin)
```

**Key Characteristics:**
- Same as BUY signal alert
- Uses same path and defaults

### 3. Order Created Alert

**Call Chain:**
```
signal_monitor.py:2819 (create_automatic_order)
    ↓
telegram_notifier.send_order_created(...)
    ↓
telegram_notifier.py:505 (send_order_created)
    ↓
telegram_notifier.send_message(message.strip())
    ↓
origin = get_runtime_origin() if origin is None
```

**Key Characteristics:**
- **File:** `backend/app/services/signal_monitor.py:2819`
- **Function:** Calls `telegram_notifier.send_order_created()`
- **Origin Parameter:** `None` (defaults in send_message)
- **Message Format:** Formatted HTML
- **Parse Mode:** HTML (default)

### 4. Monitoring Alerts (Direct send_message)

**Call Chain:**
```
signal_monitor.py:1934, 2197, 2240, 2510, 2784, 2979
    ↓
telegram_notifier.send_message(message)
    ↓
[Same path as daily report]
```

**Key Characteristics:**
- Direct call to `send_message()`
- No intermediate wrapper function
- Same defaults as daily report

## Comparison Table

| Aspect | Daily Sales Report | BUY Signal | SELL Signal | Order Created | Monitoring |
|--------|-------------------|------------|-------------|---------------|------------|
| **Entry Point** | `daily_summary.py:300` | `signal_monitor.py:1225` | `signal_monitor.py:2088` | `signal_monitor.py:2819` | `signal_monitor.py:1934+` |
| **Function Called** | `send_message()` | `send_buy_signal()` | `send_sell_signal()` | `send_order_created()` | `send_message()` |
| **Origin Parameter** | `None` | `None` | `None` | `None` | `None` |
| **Origin Resolution** | `get_runtime_origin()` | `get_runtime_origin()` | `get_runtime_origin()` | `get_runtime_origin()` | `get_runtime_origin()` |
| **Parse Mode** | HTML (default) | HTML (default) | HTML (default) | HTML (default) | HTML (default) |
| **Execution Context** | Scheduler → Thread Pool | Signal Monitor Loop | Signal Monitor Loop | Signal Monitor Loop | Signal Monitor Loop |
| **Environment** | Full AWS | Should be same | Should be same | Should be same | Should be same |

## Potential Issues

### 1. Execution Context Differences

**Daily Sales Report:**
- Runs in scheduler (scheduler.py)
- Executed via `asyncio.to_thread()` in thread pool
- Full AWS environment guaranteed

**Signal Alerts:**
- Run in signal monitor service loop
- May run in different worker process
- Environment may differ if env vars not passed to all workers

**Diagnostic:** Check if `RUNTIME_ORIGIN`, `RUN_TELEGRAM`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` are available in signal monitor execution context.

### 2. Origin Detection

All paths use the same origin detection (`get_runtime_origin()`), so if daily report works, origin detection should work for all.

**Potential Issue:** If `RUNTIME_ORIGIN` env var is missing in signal monitor context, `get_runtime_origin()` may return "LOCAL" instead of "AWS".

**Diagnostic:** Log `os.getenv("RUNTIME_ORIGIN")` in both contexts and compare.

### 3. Gatekeeper Blocking

Gatekeeper checks:
1. `origin_upper in ("AWS", "TEST")` → Must be "AWS" or "TEST"
2. `self.enabled` → Must be True
3. `bot_token_present` → Must be True
4. `chat_id_present` → Must be True

**Daily Report:** All checks pass ✅

**Other Alerts:** If any check fails, message is blocked.

**Diagnostic:** Compare `[TELEGRAM_GATEKEEPER]` logs between working and non-working alerts.

### 4. Silent Failures

Check for:
- `try/except` blocks that swallow exceptions
- Early returns before `send_message()`
- Missing error logging

**Diagnostic:** Review code for exception handling patterns.

## Diagnostic Steps

1. **Run diagnose_telegram_paths.py** in AWS to test all paths
2. **Compare [TELEGRAM_GATEKEEPER] logs** between working and non-working alerts
3. **Check environment variables** in signal monitor execution context
4. **Verify origin detection** returns "AWS" for all alerts
5. **Check for silent failures** in signal monitor exception handling

## Next Steps

1. Add diagnostic logging to compare execution contexts
2. Ensure all env vars are passed to all workers
3. Verify origin detection in signal monitor context
4. Fix any differences identified

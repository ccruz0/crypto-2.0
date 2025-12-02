# LOCAL vs AWS Alert and Order Paths

## Overview

This document describes the runtime origin system that enforces a clear separation between:
- **AWS (production)**: Real orders and official Telegram alerts
- **LOCAL (development)**: No real orders, no production Telegram alerts

## Runtime Origin Detection

The system uses a `RUNTIME_ORIGIN` environment variable to determine the runtime context:

- **`RUNTIME_ORIGIN=AWS`**: Production runtime on AWS
- **`RUNTIME_ORIGIN=LOCAL`** (or unset): Development runtime on Mac

### Configuration

**AWS Backend (docker-compose.yml):**
```yaml
environment:
  - RUNTIME_ORIGIN=AWS
```

**Local Development:**
- Defaults to `LOCAL` if not set
- Can be explicitly set: `RUNTIME_ORIGIN=LOCAL`

### Helper Functions

```python
from app.core.runtime import is_aws_runtime, is_local_runtime, get_runtime_origin

if is_aws_runtime():
    # Production logic
    pass
else:
    # Development logic
    pass
```

## Order Placement Guards

### Location
- `backend/app/services/brokers/crypto_com_trade.py`
- Functions: `place_market_order()`, `place_limit_order()`

### Behavior

**AWS Runtime:**
- Orders are placed normally (subject to `dry_run` and `live_trading` flags)

**LOCAL Runtime:**
- Orders are **blocked** with a clear log message
- Returns: `{"status": "blocked-local-runtime", "reason": "Order placement disabled on LOCAL runtime"}`
- Logs: `[ORDER_GUARD] Attempt to place order in LOCAL runtime – blocking`

### Code Example

```python
from app.core.runtime import is_aws_runtime

def place_market_order(...):
    # RUNTIME GUARD: Only AWS can place real orders
    if not is_aws_runtime() and not dry_run:
        logger.warning(
            f"[ORDER_GUARD] Attempt to place order in LOCAL runtime – blocking. "
            f"symbol={symbol}, side={side}"
        )
        return {
            "status": "blocked-local-runtime",
            "reason": "Order placement disabled on LOCAL runtime"
        }
    # ... normal order placement logic
```

## Telegram Alert Guards

### Location
- `backend/app/services/telegram_notifier.py`
- Function: `send_message()`

### Behavior

**AWS Runtime:**
- Alerts are sent to production Telegram channel
- Messages are prefixed with `[AWS]`

**LOCAL Runtime:**
- Alerts are **blocked** from reaching Telegram
- Logs: `[TG_LOCAL_DEBUG] Would send Telegram alert (blocked in LOCAL): ...`
- Still registered in dashboard with `[LOCAL DEBUG]` prefix for debugging

### Code Example

```python
from app.core.runtime import is_aws_runtime

def send_message(self, message: str, ...):
    # RUNTIME GUARD: Only AWS can send production Telegram alerts
    if not is_aws_runtime():
        logger.info(
            f"[TG_LOCAL_DEBUG] Would send Telegram alert (blocked in LOCAL): {message[:200]}"
        )
        # Register in dashboard for debugging
        add_telegram_message(f"[LOCAL DEBUG] {message}", blocked=True)
        return False
    # ... normal Telegram send logic
```

## Telegram Polling Guards

### Location
- `backend/app/services/telegram_commands.py`
- Function: `get_telegram_updates()`

### Behavior

**AWS Runtime:**
- Polls Telegram API for incoming commands
- Processes commands normally

**LOCAL Runtime:**
- **Does not poll** to avoid 409 conflicts
- Logs: `[TG_LOCAL_DEBUG] Skipping getUpdates in LOCAL runtime to avoid 409 conflicts`

### Why This Matters

Telegram only allows **one** active polling client or webhook per bot token. If both AWS and LOCAL try to poll, Telegram returns a 409 conflict error. By blocking LOCAL from polling, we ensure only AWS handles incoming commands.

## Throttling Rules

### Location
- `backend/app/services/signal_monitor.py`
- `backend/app/services/signal_throttle.py`

### Behavior

Throttling rules (1% price change OR 5-minute cooldown) are **applied uniformly** regardless of runtime origin:

- Throttling decisions are logged with origin: `[ALERT_THROTTLE_DECISION] origin=AWS|LOCAL ...`
- LOCAL still respects throttling in logs (even though alerts are blocked)
- This ensures consistent behavior and helps debug without spam

### Code Example

```python
from app.core.runtime import get_runtime_origin

buy_allowed, buy_reason = should_emit_signal(...)
if not buy_allowed:
    origin = get_runtime_origin()
    logger.info(
        f"[ALERT_THROTTLE_DECISION] origin={origin} symbol={symbol} side=BUY "
        f"allowed=False reason={buy_reason}"
    )
```

## Message Prefixes

### AWS Runtime
- All Telegram messages are prefixed with `[AWS]`
- Example: `[AWS] 🟢 BUY: BTC_USDT @ $50,000`

### LOCAL Runtime
- Messages are logged but not sent
- Dashboard shows: `[LOCAL DEBUG] 🟢 BUY: BTC_USDT @ $50,000`
- Marked as `blocked=True` in monitoring

## What Runs Where

### AWS (Production)
- ✅ SignalMonitorService (monitors signals, sends alerts)
- ✅ Order placement (via Crypto.com API)
- ✅ Telegram alert sending
- ✅ Telegram command polling (`getUpdates`)
- ✅ All background jobs (scheduler, exchange sync, etc.)

### LOCAL (Development)
- ✅ Code editing and testing
- ✅ Running tests (`pytest`, `npm test`)
- ✅ SSH-based diagnostics (`scripts/aws_backend_logs.sh`)
- ✅ Health checks (`scripts/check_runtime_health_aws.sh`)
- ❌ **NO** real order placement
- ❌ **NO** production Telegram alerts
- ❌ **NO** Telegram polling (to avoid 409 conflicts)

## Guarantees

1. **LOCAL cannot place real orders**: All order placement functions check `is_aws_runtime()` and block in LOCAL
2. **LOCAL cannot spam Telegram**: All Telegram send functions check `is_aws_runtime()` and log instead of sending
3. **No 409 conflicts**: LOCAL does not poll Telegram, only AWS does
4. **Throttling is respected everywhere**: Same throttling logic applies to both AWS and LOCAL
5. **Clear logging**: All blocked actions log `[ORDER_GUARD]` or `[TG_LOCAL_DEBUG]` for easy debugging

## Troubleshooting

### "LOCAL" alerts appearing in Monitoring

**Cause:** A script or service is running on Mac with `RUNTIME_ORIGIN` not set (defaults to LOCAL)

**Fix:** 
- Ensure `RUNTIME_ORIGIN=AWS` is set in AWS docker-compose
- Stop any local backend services that might be running
- Check logs for `[TG_LOCAL_DEBUG]` to identify the source

### Telegram 409 conflicts

**Cause:** Both AWS and LOCAL are trying to poll Telegram

**Fix:**
- Ensure LOCAL does not call `get_telegram_updates()` (runtime guard blocks it)
- Stop any local Telegram bot scripts
- Verify only AWS backend is running with `RUNTIME_ORIGIN=AWS`

### Orders not being placed on AWS

**Cause:** `RUNTIME_ORIGIN` might not be set correctly

**Fix:**
- Check AWS backend logs for `[ORDER_GUARD]` messages
- Verify `RUNTIME_ORIGIN=AWS` in docker-compose.yml
- Restart backend container: `docker compose --profile aws restart backend-aws`

## Key Code Snippets

### Runtime Origin Setting

**`backend/app/core/config.py`:**
```python
class Settings(BaseSettings):
    RUNTIME_ORIGIN: str = "LOCAL"  # Default for safety
```

**`backend/app/core/runtime.py`:**
```python
def is_aws_runtime() -> bool:
    return get_runtime_origin() == "AWS"

def is_local_runtime() -> bool:
    return not is_aws_runtime()
```

### Order Placement Guard

**`backend/app/services/brokers/crypto_com_trade.py`:**
```python
def place_market_order(...):
    if not is_aws_runtime() and not dry_run:
        logger.warning(f"[ORDER_GUARD] Attempt to place order in LOCAL runtime – blocking")
        return {"status": "blocked-local-runtime", "reason": "..."}
    # ... normal logic
```

### Telegram Alert Guard

**`backend/app/services/telegram_notifier.py`:**
```python
def send_message(self, message: str, ...):
    if not is_aws_runtime():
        logger.info(f"[TG_LOCAL_DEBUG] Would send Telegram alert (blocked in LOCAL): ...")
        return False
    # ... normal Telegram send
```

### Throttling with Origin

**`backend/app/services/signal_monitor.py`:**
```python
origin = get_runtime_origin()
logger.info(
    f"[ALERT_THROTTLE_DECISION] origin={origin} symbol={symbol} side=BUY "
    f"allowed={buy_allowed} reason={buy_reason}"
)
```

## Summary

The runtime origin system ensures:
- **AWS = Production**: Real orders, real alerts, full functionality
- **LOCAL = Development**: Safe testing, no accidental production actions, clear logging

All critical paths (orders, alerts, polling) are guarded, and throttling is respected everywhere for consistency.

## Implementation Summary

### What Happens If I Accidentally Run a Local Bot on My Mac

1. **Order Placement**: Blocked with `[ORDER_GUARD]` log, returns `blocked-local-runtime` status
2. **Telegram Alerts**: Blocked with `[TG_LOCAL_DEBUG]` log, not sent to production channel
3. **Telegram Polling**: Blocked to avoid 409 conflicts with AWS
4. **Throttling**: Still respected in logs for debugging consistency

### What Happens on AWS When a Real BUY Signal is Generated

1. **Signal Detection**: SignalMonitorService detects BUY condition
2. **Throttling Check**: Evaluates 1% price change OR 5-minute cooldown, logs with `origin=AWS`
3. **Alert Emission**: If allowed, calls `telegram_notifier.send_buy_signal()`
4. **Telegram Send**: Message sent to production channel with `[AWS]` prefix
5. **Order Placement**: If `trade_enabled=True`, order placed via Crypto.com API
6. **Logging**: All actions logged with `origin=AWS` for traceability

### Why I Will No Longer See Multiple "LOCAL" Alerts That Ignore the 1% / 5-Minute Rules

1. **Throttling is Centralized**: All alert paths go through `should_emit_signal()` which respects throttling
2. **Origin Logging**: Throttling decisions log `origin=AWS|LOCAL` so you can see where decisions are made
3. **LOCAL Blocks Alerts**: Even if throttling allows, LOCAL runtime blocks Telegram sends
4. **Consistent Behavior**: Same throttling logic applies to both AWS and LOCAL, ensuring no bypasses


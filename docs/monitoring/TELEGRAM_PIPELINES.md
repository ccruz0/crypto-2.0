# Telegram Sending Pipelines - Unified Architecture

## Overview

This document describes the unified Telegram sending architecture for all alerts and reports in the automated trading platform. **All alerts must use the same canonical path as the daily sales report**, which is the proven, working implementation.

## Working Path (Canonical) - Daily Sales Report

### Flow Diagram

```
Scheduled Task (scheduler.py)
    ↓
send_sell_orders_report() [daily_summary.py:163]
    ↓
Message Builder (builds sales report text)
    ↓
telegram_notifier.send_message(message) [telegram_notifier.py:151]
    ↓
Origin Detection: get_runtime_origin() → "AWS" in AWS
    ↓
Gatekeeper Check: origin == "AWS" → Allow
    ↓
Add [AWS] prefix if not present
    ↓
Telegram API Call: requests.post("https://api.telegram.org/bot{token}/sendMessage")
    ↓
Success: Message sent to Telegram chat
```

### Key Components

**File:** `backend/app/services/daily_summary.py`
- **Function:** `send_sell_orders_report()` (line 163)
- **Telegram Call:** `self.telegram.send_message(message)` (line 286)
- **No origin parameter:** Defaults to `get_runtime_origin()` → "AWS" in AWS

**File:** `backend/app/services/telegram_notifier.py`
- **Class:** `TelegramNotifier`
- **Method:** `send_message()` (line 151) - **CANONICAL METHOD**
- **Environment Variables:**
  - `TELEGRAM_BOT_TOKEN` - Bot token from BotFather
  - `TELEGRAM_CHAT_ID` - Target chat/channel ID
  - `RUNTIME_ORIGIN` - Set to "AWS" in AWS deployment
  - `RUN_TELEGRAM` - Set to "true" to enable Telegram sending

### Message Format

The daily sales report message format:
```
[AWS] 📊 **Reporte de Ventas - {date} {time} (Bali)**

...sales data...

⏰ Generado: {time} (Bali)
🤖 Trading Bot Automático
```

## All Alert Types - Unified Path

All alert types must route through `telegram_notifier.send_message()`:

### 1. Signal Alerts (BUY/SELL)

**File:** `backend/app/services/signal_monitor.py`
- **Calls:** `telegram_notifier.send_buy_signal()` or `telegram_notifier.send_sell_signal()`
- **Internal:** These methods call `send_message()` with proper origin
- **Status:** ✅ Uses unified path

### 2. Order Created Alerts

**File:** `backend/app/services/signal_monitor.py`
- **Calls:** `telegram_notifier.send_order_created()`
- **Internal:** Calls `send_message()` internally
- **Status:** ✅ Uses unified path

### 3. Monitoring Alerts

**File:** `backend/app/services/signal_monitor.py`
- **Calls:** `telegram_notifier.send_message()` directly
- **Status:** ✅ Uses unified path

### 4. Watchlist Alerts

**File:** `backend/app/services/signal_monitor.py`
- **Calls:** `telegram_notifier.send_buy_signal()` / `telegram_notifier.send_sell_signal()`
- **Status:** ✅ Uses unified path

### 5. CPI Alerts

**Status:** ✅ Not found in codebase (may not exist or use different name)
**Note:** If CPI alerts exist, they should use `telegram_notifier.send_message()`

### 6. Daily Sales Report

**File:** `backend/app/services/daily_summary.py`
- **Calls:** `telegram_notifier.send_message()` directly
- **Status:** ✅ **WORKING PATH (CANONICAL)**

## Telegram Notifier Implementation

### Core Method: `send_message()`

**Location:** `backend/app/services/telegram_notifier.py:151`

**Signature:**
```python
def send_message(
    self, 
    message: str, 
    reply_markup: Optional[dict] = None, 
    origin: Optional[str] = None
) -> bool
```

**Behavior:**
1. If `origin` is None, defaults to `get_runtime_origin()` (returns "AWS" in AWS)
2. Gatekeeper: Only allows "AWS" or "TEST" origins to send
3. Adds environment prefix: `[AWS]` or `[TEST]` if not present
4. Uses `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` from environment
5. Sends via Telegram API: `https://api.telegram.org/bot{token}/sendMessage`
6. Logs all attempts (success and failure)
7. Registers message in monitoring dashboard

### Helper Methods (All Route Through `send_message()`)

- `send_buy_signal()` → calls `send_message()`
- `send_sell_signal()` → calls `send_message()`
- `send_order_created()` → calls `send_message()`
- `send_executed_order()` → calls `send_message()`
- `send_sl_tp_orders()` → calls `send_message()`
- `send_message_with_buttons()` → calls `send_message()`

## Environment Configuration

### Required Environment Variables (AWS)

```bash
# Telegram Configuration (CANONICAL)
TELEGRAM_BOT_TOKEN=your_bot_token_from_botfather
TELEGRAM_CHAT_ID=your_chat_or_channel_id

# Runtime Configuration
RUNTIME_ORIGIN=AWS  # Must be "AWS" for production alerts
RUN_TELEGRAM=true   # Enable Telegram sending
```

### Local Development

```bash
# Local Development (Telegram disabled)
RUNTIME_ORIGIN=LOCAL  # or not set (defaults to LOCAL)
RUN_TELEGRAM=false    # Disable Telegram sending
```

## Direct API Calls (NOT RECOMMENDED)

The following files contain direct Telegram API calls that bypass `telegram_notifier`:

1. **`backend/app/services/telegram_commands.py`**
   - Purpose: Handle incoming Telegram bot commands (responses to user)
   - Status: ⚠️ Separate use case (bot command responses, not alerts)
   - Recommendation: Keep separate (different use case)

2. **`infra/telegram_helper.py`**
   - Purpose: Infrastructure monitoring
   - Status: ⚠️ Separate use case
   - Recommendation: Migrate to use `telegram_notifier` for consistency

3. **`backend/tools/update_telegram_commands.py`**
   - Purpose: Update bot commands menu
   - Status: ⚠️ Separate use case
   - Recommendation: Keep separate (tool, not alert)

## Logging and Diagnostics

### Log Messages

The `send_message()` method logs:

1. **Entry:** `[E2E_TEST_GATEKEEPER_IN]` - Message received
2. **Origin:** `[E2E_TEST_GATEKEEPER_ORIGIN]` - Normalized origin
3. **Gatekeeper:** `[LIVE_ALERT_GATEKEEPER]` - For BUY/SELL signals
4. **Block:** `[E2E_TEST_GATEKEEPER_BLOCK]` - If blocked (non-AWS)
5. **Sending:** `[E2E_TEST_SENDING_TELEGRAM]` - Before API call
6. **Success:** `[E2E_TEST_TELEGRAM_OK]` - Message sent successfully
7. **Error:** `[E2E_TEST_TELEGRAM_ERROR]` - If send failed
8. **Telegram API:** `[TELEGRAM_SEND]` - Standard send attempt log
9. **Telegram Error:** `[TELEGRAM_ERROR]` - API error details

### Monitoring Dashboard

All sent messages are registered in the monitoring dashboard via:
- `add_telegram_message()` in `backend/app/api/routes_monitoring.py`
- Stored in `telegram_messages` database table
- Accessible via `/api/v1/monitoring/telegram-messages` endpoint

## Testing

### Test Script

**File:** `scripts/send_test_telegram_message.py`

```python
from app.services.telegram_notifier import telegram_notifier

# Test the unified pipeline
message = "[AWS] TEST ALERT FROM SHARED PIPELINE"
success = telegram_notifier.send_message(message)
print(f"Send result: {success}")
```

### Running Tests

**Local:**
```bash
cd /Users/carloscruz/automated-trading-platform && \
docker compose exec backend python scripts/send_test_telegram_message.py
```

**AWS:**
```bash
ssh hilovivo-aws 'cd /home/ubuntu/automated-trading-platform && \
docker compose --profile aws exec backend-aws python scripts/send_test_telegram_message.py'
```

## Troubleshooting

### Alerts Not Reaching Telegram

1. **Check Environment Variables:**
   ```bash
   # In AWS container
   docker compose --profile aws exec backend-aws env | grep TELEGRAM
   docker compose --profile aws exec backend-aws env | grep RUNTIME_ORIGIN
   ```

2. **Check Logs:**
   ```bash
   # Look for gatekeeper blocks
   docker compose --profile aws logs backend-aws | grep GATEKEEPER
   # Look for send attempts
   docker compose --profile aws logs backend-aws | grep TELEGRAM_SEND
   # Look for errors
   docker compose --profile aws logs backend-aws | grep TELEGRAM_ERROR
   ```

3. **Verify Origin:**
   - Ensure `RUNTIME_ORIGIN=AWS` in AWS environment
   - Check that `get_runtime_origin()` returns "AWS"

4. **Verify Telegram Enabled:**
   - Ensure `RUN_TELEGRAM=true` in AWS environment
   - Check that `telegram_notifier.enabled == True`

## Verification Results

### All Alert Types Verified ✅

1. **Signal Alerts (BUY/SELL)** ✅
   - File: `backend/app/services/signal_monitor.py`
   - Uses: `telegram_notifier.send_buy_signal()` / `telegram_notifier.send_sell_signal()`
   - Routes through: `send_message()`

2. **Order Created Alerts** ✅
   - Files: `backend/app/services/signal_monitor.py`, `backend/app/api/routes_orders.py`
   - Uses: `telegram_notifier.send_order_created()`
   - Routes through: `send_message()`

3. **Monitoring Alerts** ✅
   - File: `backend/app/services/signal_monitor.py`
   - Uses: `telegram_notifier.send_message()` directly
   - Routes through: `send_message()`

4. **Watchlist Alerts** ✅
   - File: `backend/app/services/signal_monitor.py`
   - Uses: `telegram_notifier.send_buy_signal()` / `telegram_notifier.send_sell_signal()`
   - Routes through: `send_message()`

5. **Daily Sales Report** ✅
   - File: `backend/app/services/daily_summary.py`
   - Uses: `telegram_notifier.send_message()` directly
   - **WORKING PATH (CANONICAL)**

6. **Manual Trade Alerts** ✅
   - File: `backend/app/api/routes_manual_trade.py`
   - Uses: `telegram_notifier.send_buy_alert()`, `telegram_notifier.send_sl_tp_orders()`
   - Routes through: `send_message()`

7. **Test Alerts** ✅
   - File: `backend/app/api/routes_test.py`
   - Uses: `telegram_notifier.send_message()`, `telegram_notifier.send_buy_signal()`, etc.
   - Routes through: `send_message()`

### Direct API Calls (Separate Use Cases)

The following files contain direct Telegram API calls but are for **different purposes** (bot command responses, not alerts):

- `backend/app/services/telegram_commands.py` - Bot command handler (responses to user commands)
- `infra/telegram_helper.py` - Infrastructure monitoring (could be migrated for consistency)
- `backend/tools/update_telegram_commands.py` - Bot commands menu update tool

**Recommendation:** These are acceptable as separate use cases, but `infra/telegram_helper.py` could be migrated to use `telegram_notifier` for consistency.

## Summary

- **Canonical Path:** `telegram_notifier.send_message()` in `telegram_notifier.py`
- **All Alerts:** ✅ Route through this single method
- **Environment:** Uses `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID`
- **Origin:** Defaults to `get_runtime_origin()` → "AWS" in AWS
- **Logging:** Comprehensive logging for diagnostics
- **Monitoring:** All messages registered in dashboard

**Key Principle:** If the daily sales report works, all other alerts using the same path will work too.

**Status:** ✅ All alert types verified to use unified path

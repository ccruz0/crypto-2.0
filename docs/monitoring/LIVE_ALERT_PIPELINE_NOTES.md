# Live Alert Pipeline Documentation

## Overview

This document maps the complete flow of live trading alerts from signal detection to Telegram delivery and Monitoring registration.

## Pipeline Flow

### 1. Signal Detection (`signal_monitor.py`)

**Entry Point:** `SignalMonitorService._check_signal_for_coin_sync()`

**Process:**
1. **Strategy Evaluation** (lines ~1000-1040)
   - Calls `calculate_trading_signals()` to evaluate strategy rules
   - Gets `decision` (BUY/SELL/WAIT) and `buy_signal`/`sell_signal` flags
   - Logs: `decision={decision} | buy_signal={buy_signal} | sell_signal={sell_signal}`

2. **Throttling Check** (lines ~1100-1200)
   - For BUY: Calls `should_emit_signal()` with throttle config
   - For SELL: Calls `should_emit_signal()` with throttle config
   - Logs: `[ALERT_THROTTLE_DECISION] origin={origin} symbol={symbol} side={side} allowed={allowed} reason={reason}`
   - If throttled: Sets `buy_signal=False` or `sell_signal=False`
   - **CRITICAL:** Blocked signals are registered in Monitoring with `blocked=True` (lines 1195-1203 for SELL, similar for BUY)

3. **Flag Check** (lines ~1217-1250 for BUY, ~2361-2393 for SELL)
   - Calls `_evaluate_alert_flag()` to check `alert_enabled` and `buy_alert_enabled`/`sell_alert_enabled`
   - Logs: `🔍 {symbol} BUY/SELL alert decision: ... DECISION: SENT/SKIPPED`
   - If flags block: Logs rejection and registers in Monitoring with `blocked=True`

### 2. Alert Emission (`signal_monitor.py`)

**BUY Alerts** (lines ~1400-1610):
- **Final Flag Check** (lines ~1380-1410)
  - Re-checks flags from database
  - If blocked: Registers in Monitoring with `blocked=True` and exits
- **Portfolio Risk Check** (lines ~1418-1519)
  - **CRITICAL:** Only blocks ORDER CREATION, NOT alerts
  - Sets `should_send = True` (line 1415)
  - Alerts are ALWAYS sent when `decision=BUY` and flags allow
- **Telegram Send** (lines ~1521-1607)
  - Gets `origin = get_runtime_origin()` (line 1544)
  - Calls `telegram_notifier.send_buy_signal(..., origin=origin)` (line 1545)
  - Logs: `[ALERT_EMIT_FINAL] origin={origin} symbol={symbol} | side=BUY | status=success/telegram_api_failed`
  - **Monitoring:** Registered in `send_buy_signal()` if result is True

**SELL Alerts** (lines ~2400-2576):
- **Final Flag Check** (lines ~2474-2502)
  - Re-checks flags from database
  - If blocked: Registers in Monitoring with `blocked=True` and exits
- **Telegram Send** (lines ~2504-2576)
  - Gets `origin = get_runtime_origin()` (line 2519)
  - Calls `telegram_notifier.send_sell_signal(..., origin=origin)` (line 2520)
  - Logs: `[ALERT_EMIT_FINAL] origin={origin} symbol={symbol} | side=SELL | status=success/telegram_api_failed`
  - **Monitoring:** Registered in `send_sell_signal()` if result is True

### 3. Telegram Delivery (`telegram_notifier.py`)

**Entry Point:** `send_buy_signal()` or `send_sell_signal()`

**Process:**
1. **Message Construction** (lines ~688-778 for BUY, ~780-863 for SELL)
   - Builds formatted message with strategy details
   - Sets `source="LIVE ALERT"` for live alerts
   - Gets `origin = get_runtime_origin()` if not provided (lines 759, 844)

2. **Send Message** (line 761 for BUY, line 846 for SELL)
   - Calls `send_message(message, origin=origin)`

3. **Gatekeeper** (`send_message()`, lines ~151-334)
   - **Origin Check** (lines ~176-223)
     - Normalizes origin to uppercase
     - **BLOCKS** if `origin_upper not in ("AWS", "TEST")`
     - Logs: `[E2E_TEST_GATEKEEPER_BLOCK]` for blocked origins
   - **Enabled Check** (lines ~225-229)
     - Checks `self.enabled` (requires `RUN_TELEGRAM=true` AND credentials)
     - Logs: `[E2E_TEST_CONFIG] Telegram sending disabled` if false
   - **Telegram API Call** (lines ~231-320)
     - For AWS: Adds `[AWS]` prefix
     - For TEST: Adds `[TEST]` prefix
     - Sends to Telegram API
     - Logs: `[E2E_TEST_TELEGRAM_OK]` on success, `[E2E_TEST_TELEGRAM_ERROR]` on failure
   - **Monitoring Registration** (lines ~302-318)
     - Calls `add_telegram_message(display_message, symbol=symbol, blocked=False)`
     - Only called if Telegram send succeeded

### 4. Monitoring Registration (`routes_monitoring.py`)

**Function:** `add_telegram_message()`

**Process:**
1. **Logging** (line 165)
   - Logs: `[E2E_TEST_MONITORING_SAVE] message_preview={message[:80]}, symbol={symbol}, blocked={blocked}`

2. **Database Save** (lines ~185-243)
   - Saves to `TelegramMessage` table
   - Includes `blocked`, `throttle_status`, `throttle_reason`
   - Deduplicates messages within 5 seconds

## Key Decision Points

### Where BUY/SELL Decision is Made
- **Function:** `calculate_trading_signals()` in `trading_signals.py`
- **Returns:** `decision` (BUY/SELL/WAIT) and `buy_signal`/`sell_signal` flags
- **Location in SignalMonitor:** Lines ~1000-1040

### Where Alert Emission is Triggered
- **Function:** `telegram_notifier.send_buy_signal()` or `send_sell_signal()`
- **Called from:** `signal_monitor.py` lines 1545 (BUY) and 2520 (SELL)
- **Condition:** `should_send=True` AND flags allow

### Where Monitoring is Updated
- **Sent Alerts:** `send_buy_signal()`/`send_sell_signal()` calls `add_telegram_message()` after successful Telegram send (lines 764-776, 849-861)
- **Blocked Alerts:** 
  - Throttled: `signal_monitor.py` lines 1195-1203 (SELL), similar for BUY
  - Flag-blocked: `signal_monitor.py` lines 1403-1406 (BUY), 2496-2500 (SELL)

## Potential Blockers

1. **SignalMonitorService Not Running**
   - Check: `main.py` startup event
   - Check: AWS logs for service crashes

2. **Throttling**
   - Check: `should_emit_signal()` database queries
   - Check: `[ALERT_THROTTLE_DECISION]` logs

3. **Flag Checks**
   - Check: `_evaluate_alert_flag()` results
   - Check: Database values for `alert_enabled`, `buy_alert_enabled`, `sell_alert_enabled`

4. **Origin Issues**
   - Check: `get_runtime_origin()` returns "AWS" on AWS
   - Check: `RUNTIME_ORIGIN` environment variable

5. **Telegram Gatekeeper**
   - Check: `telegram_notifier.enabled` is True
   - Check: Credentials are set
   - Check: Origin is "AWS" or "TEST"

6. **Monitoring Not Called**
   - Check: `add_telegram_message()` is called for both sent and blocked alerts
   - Check: Database connection works


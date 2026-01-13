# Monitor UI Inconsistency - Analysis

## Current State

### Active Alerts Endpoint
- **Endpoint**: `GET /monitoring/summary`
- **Source**: Watchlist state + signal calculations
- **Logic**: Shows alerts where:
  - `buy_alert_enabled` or `sell_alert_enabled` is True
  - BUY/SELL signal is calculated as active
  - Message: "Buy alert active for {symbol} (signal detected)"
- **Problem**: Shows "signal detected" but no telegram_messages row exists (not sent/blocked/failed)

### Throttle Messages Sent
- **Endpoint**: `GET /monitoring/signal-throttle`
- **Source**: `telegram_messages` table (blocked=False, contains "BUY SIGNAL" or "SELL SIGNAL")
- **Logic**: Shows messages that were actually sent to Telegram

## Issue
- Active Alerts shows 3 BUY alerts with "signal detected"
- Throttle Messages Sent shows no messages for those alerts
- User expectation: If alert is shown as active, must show why it did NOT send (blocked/failed) OR show it as sent

## Proposed Solution

Change Active Alerts to be derived from `telegram_messages` + `order_intents` instead of Watchlist state.

**New Definition**:
- "Active Alerts" = last X minutes of BUY/SELL signals that were:
  - SENT (blocked=false) OR
  - BLOCKED/FAILED (blocked=true or decision_type indicates skip/failure)

**Return per row**:
- symbol, side, timestamp
- alert_status (SENT/BLOCKED/FAILED)
- decision_type, reason_code, reason_message
- message_id (telegram_messages.id)
- order_intent_status (ORDER_PLACED/ORDER_FAILED/DEDUP_SKIPPED) if exists

**Counts**:
- active_total
- sent_count
- blocked_count
- failed_count

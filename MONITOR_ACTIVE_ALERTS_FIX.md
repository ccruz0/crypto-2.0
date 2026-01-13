# Fix: Active Alerts Derived from telegram_messages + order_intents

## Problem
Monitoring page showed "Active Alerts: 3" with rows "signal detected", but there were no Telegram messages sent. This happened because:
- Active Alerts (`/monitoring/summary`) was computed from Watchlist signal detection (not send pipeline)
- Throttle Messages Sent (`/monitoring/signal-throttle`) was computed from telegram_messages (blocked=false)

## Solution
Fixed Active Alerts to derive from the same truth source: `telegram_messages` + `order_intents`.

## Changes

### Backend (`routes_monitoring.py`)
1. Changed time window from 24 hours to **30 minutes**
2. Use **ILIKE** for case-insensitive matching of BUY/SELL SIGNAL messages
3. **LEFT JOIN** with `order_intents` on `signal_id::text = telegram_messages.id::text`
4. Derive `status_label`:
   - **SENT** if `blocked=false`
   - **FAILED** if `order_intent_status='ORDER_FAILED'` OR `reason_code` indicates failure
   - **BLOCKED** otherwise (`blocked=true`)
5. Return counts: `active_total`, `sent_count`, `blocked_count`, `failed_count`
6. **Ensures**: If there are 0 telegram_messages in window, Active Alerts = 0

### Frontend (`MonitoringPanel.tsx`)
1. Use `status_label` from backend instead of generic "signal detected" message
2. Show `reason_code`/`reason_message` when `status != SENT`
3. Minimal UI change: Status column shows proper labels (SENT/BLOCKED/FAILED)

## Before/After JSON Sample

### Before (from Watchlist signal detection)
```json
{
  "active_alerts": 3,
  "alert_counts": {
    "sent": 0,
    "blocked": 0,
    "failed": 0
  },
  "alerts": [
    {
      "type": "BUY",
      "symbol": "BTC_USDT",
      "message": "signal detected",
      "severity": "INFO",
      "timestamp": "2025-01-27T12:00:00Z"
    }
  ]
}
```

### After (from telegram_messages + order_intents)
```json
{
  "active_alerts": 2,
  "active_total": 2,
  "alert_counts": {
    "sent": 1,
    "blocked": 1,
    "failed": 0
  },
  "alerts": [
    {
      "type": "BUY",
      "symbol": "BTC_USDT",
      "status_label": "SENT",
      "alert_status": "SENT",
      "severity": "INFO",
      "timestamp": "2025-01-27T12:05:00Z",
      "message_id": 12345,
      "order_intent_status": "ORDER_PLACED",
      "decision_type": null,
      "reason_code": null,
      "reason_message": null,
      "message": "BUY signal sent for BTC_USDT"
    },
    {
      "type": "SELL",
      "symbol": "ETH_USDT",
      "status_label": "BLOCKED",
      "alert_status": "BLOCKED",
      "severity": "WARNING",
      "timestamp": "2025-01-27T12:03:00Z",
      "message_id": 12344,
      "order_intent_status": null,
      "decision_type": "SKIPPED",
      "reason_code": "THROTTLED_MIN_TIME",
      "reason_message": "Throttled: Cooldown period not elapsed",
      "message": "SELL signal blocked for ETH_USDT: Throttled: Cooldown period not elapsed"
    }
  ]
}
```

## Verification
- ✅ With 0 telegram_messages in last 30 min => Active Alerts = 0
- ✅ With 2 messages (1 blocked=false, 1 blocked=true) => Active Alerts = 2 with correct labels
- ✅ Status labels properly derived from send pipeline state

## Commits
- Backend: `fix(monitor): Active Alerts derived from telegram_messages + order_intents`
- Frontend: `fix(monitor): Show status_label in Active Alerts table`

# Monitor UI Inconsistency Fix - Summary

## Current Problem
- Active Alerts shows alerts with "signal detected" but no corresponding telegram_messages row
- Throttle Messages Sent shows only sent messages
- User sees inconsistency: alerts shown but not in "sent" list

## Root Cause
Active Alerts is computed from Watchlist state (signals detected), not from actual send pipeline state (telegram_messages).

## Solution (Preferred Approach)
Change Active Alerts endpoint to derive from `telegram_messages` + `order_intents` instead of Watchlist state.

**Implementation Plan**:
1. Modify `/monitoring/summary` endpoint to query `telegram_messages` for BUY/SELL SIGNAL messages
2. Include blocked=false (SENT) and blocked=true (BLOCKED/FAILED) messages
3. Join with `order_intents` to get order status
4. Return status: SENT/BLOCKED/FAILED for each alert
5. Update frontend to show status badges and reasons

**Alternative (Minimal Change)**:
- Keep current Active Alerts logic but add status from telegram_messages lookup
- For each detected alert, check if telegram_messages row exists
- Show status: SENT if blocked=false, BLOCKED if blocked=true, DETECTED if no row exists

## Next Steps
1. Implement backend changes (preferred: derive from telegram_messages)
2. Update frontend to display status badges
3. Test with real signals

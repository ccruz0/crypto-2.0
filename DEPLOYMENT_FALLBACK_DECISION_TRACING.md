# Deployment: Fallback Decision Tracing

## Deployment Date
2026-01-09

## Changes Deployed

### Code Changes
1. **Fallback Decision Tracing Mechanism** (`backend/app/services/signal_monitor.py`)
   - Added fallback decision tracing when `should_create_order=False` and `buy_alert_sent_successfully=True`
   - Ensures decision tracing is always recorded even if guard clauses fail silently
   - Works for both BUY and SELL orders

### Documentation Updates
1. **Order Lifecycle Guide** (`docs/ORDER_LIFECYCLE_GUIDE.md`)
   - Added "Order Creation Sequence" section
   - Clarified that SELL orders are automatically created
   - Updated scenarios to show complete sequence: Alert → Order → SL/TP

2. **Decision Tracing Summary** (`DECISION_TRACING_COMPLETE_SUMMARY.md`)
   - Updated to mention both BUY and SELL orders
   - Added complete sequence documentation

3. **Fallback Fix Documentation** (`FALLBACK_DECISION_TRACING_FIX.md`)
   - Clarified SELL orders also create automatic orders

## Deployment Steps

1. ✅ Code pulled from main branch
2. ✅ Market-updater-aws service restarted
3. ✅ Service status verified

## Verification

After deployment, verify:
1. Service is running: `docker compose --profile aws ps market-updater-aws`
2. Check logs for errors: `docker compose --profile aws logs --tail 100 market-updater-aws`
3. Wait for next alert and verify decision tracing appears in Monitor UI

## Expected Behavior

When an alert is sent but order is blocked:
- Primary decision tracing is emitted in guard clauses (as before)
- If that fails, fallback ensures decision tracing is recorded
- Monitor UI shows blocked entry with decision_type, reason_code, reason_message

## Rollback

If issues occur, rollback to previous commit:
```bash
git checkout <previous-commit-hash>
docker compose --profile aws restart market-updater-aws
```

---

**Status:** ✅ Deployed  
**Commit:** 7a44b10


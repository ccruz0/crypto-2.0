# BUY SIGNAL Decision Tracing Fix - Deployment Summary

## ✅ Implementation Complete

All code changes have been implemented and are ready for deployment.

## Files Changed

1. **backend/app/api/routes_monitoring.py**
   - Added `update_telegram_message_decision_trace()` function
   - Added `GET /api/diagnostics/recent-buy-signals` endpoint
   - Added `POST /api/diagnostics/run-signal-order-test` endpoint

2. **backend/app/services/signal_monitor.py**
   - Updated guard clauses to update original BUY SIGNAL messages
   - Updated ORDER_CREATED handler to update original message
   - Updated ORDER_FAILED handler to update original message
   - Enhanced fallback safety net

3. **backend/app/utils/decision_reason.py**
   - Added `DecisionType.EXECUTED`
   - Added `ReasonCode.EXEC_ORDER_PLACED`
   - Added `ReasonCode.DECISION_PIPELINE_NOT_CALLED`
   - Added `make_execute()` function

## Deployment Options

### Option 1: Automated Script (Recommended)
```bash
./deploy_decision_tracing_fix.sh
```

### Option 2: Manual Deployment
```bash
# 1. Sync files to AWS
rsync -avz -e "ssh -i ~/.ssh/id_rsa" \
  backend/app/api/routes_monitoring.py \
  backend/app/services/signal_monitor.py \
  backend/app/utils/decision_reason.py \
  ubuntu@your-aws-server:~/automated-trading-platform/backend/app/

# 2. SSH to server
ssh ubuntu@your-aws-server

# 3. Restart market-updater
cd ~/automated-trading-platform/backend
pkill -f "run_updater.py" || true
nohup python3 run_updater.py > market_updater.log 2>&1 &

# 4. Restart backend API (if running directly)
pkill -f "uvicorn app.main:app" || true
nohup python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8000 > backend.log 2>&1 &
```

### Option 3: Git-Based Deployment
If you use git on AWS:
```bash
# On AWS server
cd ~/automated-trading-platform
git pull origin main
# Then restart processes as above
```

## Post-Deployment Verification

### 1. Check Diagnostics Endpoint
```bash
curl http://your-aws-server:8000/api/diagnostics/recent-buy-signals?limit=10
```

Expected: All BUY SIGNAL messages should have non-null `decision_type`

### 2. Run Self-Test
```bash
curl -X POST "http://your-aws-server:8000/api/diagnostics/run-signal-order-test?dry_run=true"
```

Expected: Returns structured report showing pipeline steps

### 3. Check Process Logs
```bash
# On AWS server
tail -50 ~/automated-trading-platform/backend/market_updater.log | grep -i "decision\|buy signal"
```

Look for:
- `[DECISION]` log entries
- `update_telegram_message_decision_trace` messages
- No errors related to decision tracing

### 4. Database Verification (Optional)
```sql
-- Check for BUY SIGNAL messages with NULL decision_type (should be 0 after deployment)
SELECT COUNT(*) 
FROM telegram_messages 
WHERE message LIKE '%BUY SIGNAL%' 
  AND decision_type IS NULL
  AND timestamp >= NOW() - INTERVAL '24 hours';

-- View recent BUY SIGNAL messages with decision traces
SELECT 
    id,
    symbol,
    LEFT(message, 100) as message_preview,
    timestamp,
    decision_type,
    reason_code,
    LEFT(reason_message, 100) as reason_preview
FROM telegram_messages
WHERE message LIKE '%BUY SIGNAL%'
  AND timestamp >= NOW() - INTERVAL '24 hours'
ORDER BY timestamp DESC
LIMIT 20;
```

## Expected Behavior After Deployment

### For New BUY SIGNAL Messages:

1. **SKIPPED** - Order was blocked before attempt
   - `decision_type`: "SKIPPED"
   - `reason_code`: One of: MAX_OPEN_TRADES_REACHED, RECENT_ORDERS_COOLDOWN, TRADE_DISABLED, etc.
   - `reason_message`: Human-readable explanation
   - `context_json`: Structured data (counts, timestamps, etc.)

2. **FAILED** - Order was attempted but failed
   - `decision_type`: "FAILED"
   - `reason_code`: One of: EXCHANGE_REJECTED, INSUFFICIENT_FUNDS, AUTHENTICATION_ERROR, etc.
   - `reason_message`: Human-readable explanation
   - `exchange_error_snippet`: Raw exchange error message
   - `context_json`: Structured data

3. **EXECUTED** - Order was successfully created
   - `decision_type`: "EXECUTED"
   - `reason_code`: "EXEC_ORDER_PLACED"
   - `reason_message`: Success message with order_id
   - `context_json`: Contains order_id, exchange_order_id, price, quantity

## Troubleshooting

### Issue: Diagnostics endpoint returns 404
**Solution**: Restart backend API process to load new routes

### Issue: Decision tracing still NULL
**Check**:
1. Market-updater process is running: `pgrep -f run_updater.py`
2. Check logs for errors: `tail -100 market_updater.log`
3. Verify files were synced correctly
4. Ensure process was restarted after deployment

### Issue: Process won't start
**Check**:
1. Python dependencies: `pip list | grep fastapi`
2. Database connection: Check DATABASE_URL in .env
3. Port availability: `netstat -tuln | grep 8000`

## Monitoring

After deployment, monitor:
1. New BUY SIGNAL messages appear with decision traces
2. No new NULL decision_type messages
3. Orders are created when conditions are met
4. Logs show `[DECISION]` entries

## Rollback Plan

If issues occur, you can:
1. Restore previous version of the 3 files from git
2. Restart processes
3. Old behavior will resume (NULL decision_type, but system continues to work)

## Success Criteria

✅ Deployment is successful when:
- No BUY SIGNAL messages have NULL decision_type (after new signals)
- Diagnostics endpoint returns data
- Self-test endpoint works
- Market-updater process runs without errors
- Orders are created when `should_create_order=True`

## Next Steps After Deployment1. Monitor first few BUY SIGNAL messages to verify decision traces
2. Test diagnostics endpoint in browser/Postman
3. Run self-test to verify pipeline
4. Check logs for any errors
5. Verify orders are being created correctly

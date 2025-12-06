# Debug Strategy - FLIP DETECTED Analysis

**Date:** 2025-11-30  
**Symbol:** ALGO_USDT  
**Status:** No logs found

## Summary

Attempted to capture FLIP DETECTED events for `ALGO_USDT` using the remote debug script, but no `DEBUG_STRATEGY_FINAL` logs were found in the container.

## Execution Details

### Script Configuration
- **Remote Host:** `hilovivo-aws`
- **Remote User:** `ubuntu`
- **Project Directory:** `/home/ubuntu/automated-trading-platform`
- **Backend Service:** `backend-aws`
- **Container:** `automated-trading-platform-backend-aws-1` (ID: `4da09ea4cd4ca745ce8b5aab0145a11ee4d3986bdcd2d5ab7873ac541524892c`)

### Commands Executed

```bash
# From Mac terminal
cd /Users/carloscruz/automated-trading-platform
bash scripts/debug_strategy_remote.sh ALGO_USDT 100
```

### Results

```
[REMOTE DEBUG] Running on ubuntu@hilovivo-aws
[REMOTE DEBUG] Symbol: ALGO_USDT
[REMOTE DEBUG] Last N: 100
[REMOTE DEBUG] Command: cd "/home/ubuntu/automated-trading-platform" && CONTAINER_NAME=$(docker compose ps -q "backend-aws") && python3 backend/scripts/debug_strategy.py "ALGO_USDT" --compare --last "100" --container "$CONTAINER_NAME"

🔍 Fetching strategy logs for ALGO_USDT...
   Container: 4da09ea4cd4ca745ce8b5aab0145a11ee4d3986bdcd2d5ab7873ac541524892c
   Last 100 entries

❌ No logs found for ALGO_USDT
```

## Investigation

### Log Analysis
- **Total DEBUG_STRATEGY logs in container:** 0
- **ALGO_USDT related logs:** Found (watchlist updates, alert updates)
- **DEBUG_STRATEGY_FINAL logs:** None found for any symbol

### Possible Reasons

1. **Logging Not Enabled**
   - The `DEBUG_STRATEGY_FINAL` log is at `logger.info()` level
   - May require specific log level configuration

2. **Function Not Being Called**
   - `calculate_trading_signals()` may not be invoked for ALGO_USDT
   - Symbol may not be in active watchlist evaluation

3. **Container Restart**
   - Container was restarted 11 minutes before analysis
   - Previous logs may have been cleared

4. **Log Rotation**
   - Docker logs may have been rotated/cleared
   - Historical logs not available

## Next Steps

To capture FLIP DETECTED events:

1. **Verify Logging Configuration**
   ```bash
   cd /Users/carloscruz/automated-trading-platform && bash scripts/aws_backend_logs.sh 2>&1 | grep -i 'log.*level\|logging' | head -5
   ```

2. **Trigger Strategy Evaluation**
   - Ensure ALGO_USDT is in watchlist with `alert_enabled=True`
   - Call signals API endpoint to trigger evaluation:
     ```bash
     curl 'http://localhost:8002/api/signals?exchange=CRYPTO_COM&symbol=ALGO_USDT'
     ```

3. **Wait for Multiple Evaluations**
   - Strategy evaluations happen periodically
   - Wait for several evaluation cycles to capture transitions

4. **Check Signal Monitor**
   - Verify `signal_monitor.py` is running and evaluating symbols
   - Check if ALGO_USDT is in the evaluation queue

## Script Location

- **Remote Script:** `scripts/debug_strategy_remote.sh`
- **Backend Script:** `backend/scripts/debug_strategy.py`
- **Logging Code:** `backend/app/services/trading_signals.py:674-689`

## Expected Output Format

When FLIP DETECTED events are found, the output should include:

```
⚠️  FLIP DETECTED between Entry #1 and Entry #2
   BUY → WAIT
   buy_target_ok: True → False
     ⚠️  This flag going False caused BUY → WAIT!
     Entry #1: price=0.14280500, buy_target=0.14281000, diff=-0.00000500
     Entry #2: price=0.14282100, buy_target=0.14281000, diff=+0.00001100
```

## Notes

- Script is properly configured and executable
- SSH connection to remote server works correctly
- Container is running and healthy
- Debug script executes successfully but finds no logs
- Need to investigate why `DEBUG_STRATEGY_FINAL` logs are not being generated


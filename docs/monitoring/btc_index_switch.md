# BTC Index Alerts Global Switch

**Date:** 2025-11-29  
**Status:** ✅ IMPLEMENTED

## Overview

The BTC BUY INDEX alerts can be globally enabled or disabled using the `ENABLE_BTC_INDEX_ALERTS` environment variable.

## Configuration

### Environment Variable

- **Variable**: `ENABLE_BTC_INDEX_ALERTS`
- **Type**: Boolean (string: "true" or "false")
- **Default**: `false` (alerts disabled by default in production)
- **Location**: Set in `docker-compose.yml` for backend-aws service

### How to Enable/Disable

#### Disable BTC Index Alerts (Default)
```yaml
environment:
  - ENABLE_BTC_INDEX_ALERTS=false
```

Or simply omit the variable (defaults to `false`).

#### Enable BTC Index Alerts
```yaml
environment:
  - ENABLE_BTC_INDEX_ALERTS=true
```

Or set it in `.env.aws`:
```
ENABLE_BTC_INDEX_ALERTS=true
```

## Behavior

### When Disabled (`ENABLE_BTC_INDEX_ALERTS=false`)
- BuyIndexMonitorService still runs and calculates the BTC index internally
- **No Telegram messages are sent** for "BTC_USD BUY INDEX" alerts
- Logs show: `[BUY_INDEX_DISABLED] BTC index alerts are disabled by config (ENABLE_BTC_INDEX_ALERTS=false)`
- The monitor continues to track index values but does not emit alerts

### When Enabled (`ENABLE_BTC_INDEX_ALERTS=true`)
- BuyIndexMonitorService calculates and sends BTC index alerts to Telegram
- Alerts respect existing throttling rules (price change, time cooldown)
- Normal "BTC_USD BUY INDEX" messages are sent when conditions are met

## Implementation

The check is performed at the very beginning of `BuyIndexMonitorService.send_buy_index()`:

```python
async def send_buy_index(self, db: Session):
    """Calculate and send buy index to Telegram"""
    # Check global switch - if disabled, return early without sending alerts
    if not ENABLE_BTC_INDEX_ALERTS:
        logger.debug(
            "[BUY_INDEX_DISABLED] BTC index alerts are disabled by config (ENABLE_BTC_INDEX_ALERTS=false)"
        )
        return
    # ... rest of the method
```

## Verification

To verify the switch is working:

1. **Check logs** for `[BUY_INDEX_DISABLED]` entries:
   ```bash
   cd /Users/carloscruz/automated-trading-platform && bash scripts/aws_backend_logs.sh | grep BUY_INDEX_DISABLED
   ```

2. **Monitor Telegram Messages** in the dashboard:
   - With `ENABLE_BTC_INDEX_ALERTS=false`: No new "BTC_USD BUY INDEX" alerts should appear
   - With `ENABLE_BTC_INDEX_ALERTS=true`: Alerts should appear when throttling allows

3. **Check environment variable**:
   ```bash
   docker exec automated-trading-platform-backend-aws-1 env | grep ENABLE_BTC_INDEX_ALERTS
   ```

## Files Changed

- `backend/app/services/buy_index_monitor.py`: Added global switch check
- `docker-compose.yml`: Added `ENABLE_BTC_INDEX_ALERTS` environment variable (default: false)

## Notes

- The switch only affects Telegram alerts, not internal index calculations
- Throttling rules still apply when alerts are enabled
- The default is `false` to prevent alert spam in production



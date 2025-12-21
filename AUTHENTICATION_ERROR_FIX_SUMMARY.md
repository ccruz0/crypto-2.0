# Authentication Error Handling Fix - Summary

## Problem
When authentication errors occurred during automatic order creation, users received duplicate error messages:
1. A specific authentication error message from `_create_buy_order`
2. A redundant generic "orden no creada" message from the test alert handler

Additionally, the system was attempting unnecessary SPOT fallback attempts for authentication errors, which would always fail since authentication errors indicate configuration issues (API keys, IP whitelist) that cannot be fixed by changing order types.

## Solution
Implemented early detection and specific handling of authentication errors:

### Changes Made

1. **`backend/app/services/signal_monitor.py`**:
   - Added authentication error detection in `_create_buy_order` and `_create_sell_order` methods
   - Detects errors: 401, 40101, 40103, "Authentication failed", "Authentication failure"
   - Returns error details dict `{"error": "authentication", "error_type": "authentication", "message": error_msg}` instead of `None`
   - Sends specific Telegram notification with troubleshooting steps
   - Skips SPOT fallback attempts for authentication errors (they will always fail)

2. **`backend/app/api/routes_test.py`**:
   - Updated test alert handlers to detect authentication errors
   - Skips sending generic "orden no creada" message when authentication error was already handled
   - Applies to both BUY and SELL order handlers

### Benefits
- ✅ Single, clear error message instead of duplicate messages
- ✅ Actionable troubleshooting steps (check API keys, IP whitelist, permissions)
- ✅ No unnecessary fallback attempts that waste time and resources
- ✅ Better error categorization for debugging

## Testing
To verify the fix works:

1. **Test with authentication error**:
   - Trigger a test alert with invalid API credentials or IP not whitelisted
   - Verify only ONE error message is sent (the specific authentication error message)
   - Verify the message includes troubleshooting steps

2. **Test with other errors**:
   - Trigger a test alert with insufficient balance
   - Verify generic error messages still work for non-authentication errors

## Deployment
Changes committed in commit `821e4cc`.

To deploy:
```bash
# On AWS server
cd ~/automated-trading-platform
git pull origin main
docker compose restart backend-aws
```

## Files Changed
- `backend/app/services/signal_monitor.py` (+85 lines)
- `backend/app/api/routes_test.py` (+29 lines, -3 lines)

## Related Issues
- Fixes duplicate error messages for authentication failures
- Improves user experience with clearer error messages
- Reduces unnecessary API calls (no SPOT fallback for auth errors)


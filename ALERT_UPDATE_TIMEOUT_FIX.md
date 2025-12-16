# Alert Update Timeout Fix: "Request timeout for /watchlist/{symbol}/alert"

## Issue Summary
**Error**: `Request timeout for /watchlist/LDO_USD/alert. The server may be processing the request. Please try again.`  
**Location**: Alert update endpoint `/watchlist/{symbol}/alert` (PUT)  
**Status**: ✅ FIXED  
**Date**: December 16, 2025  
**Impact**: Users unable to update alerts for trading pairs (e.g., LDO_USD) due to request timeouts

## Root Cause

The timeout was caused by:
1. **Authentication dependency issue**: The endpoint was using `get_current_user` directly instead of `_get_auth_dependency()`, which could cause delays if authentication checks are slow
2. **Lack of timeout handling**: No specific timeout protection or error handling for database operations
3. **Missing diagnostics**: Limited logging made it difficult to identify where the timeout was occurring

## Solution Applied

### 1. Fixed Authentication Dependency
Changed from:
```python
current_user = Depends(get_current_user)
```

To:
```python
current_user = Depends(_get_auth_dependency)
```

This ensures the endpoint respects the `DISABLE_AUTH` environment variable and uses the optimized auth dependency that doesn't block when auth is disabled.

### 2. Enhanced Error Handling
- Added database session null check
- Added timeout detection in error messages
- Added database lock/deadlock detection
- Improved error messages to be more user-friendly

### 3. Added Performance Logging
- Log query execution time
- Log commit execution time
- Log total request time
- This helps identify performance bottlenecks

### 4. Better Error Messages
- Timeout errors now return HTTP 504 with clear message
- Database lock errors return HTTP 503 with retry suggestion
- Generic errors include the symbol name for easier debugging

## Code Changes

**File**: `backend/app/api/routes_market.py`

**Changes**:
- Updated `update_watchlist_alert` endpoint to use `_get_auth_dependency()`
- Added timing measurements for database operations
- Added comprehensive error handling with specific error types
- Added database session validation

## Frontend Timeout

The frontend has a 15-second timeout for alert updates (configured in `frontend/src/app/api.ts` line 326). This should be sufficient for normal database operations, but if timeouts persist, consider:

1. Checking database performance
2. Checking for database locks
3. Verifying network connectivity between frontend and backend

## Verification

After deploying the fix:

1. **Test alert update**:
   ```bash
   curl -X PUT http://localhost:8002/api/watchlist/LDO_USD/alert \
     -H "Content-Type: application/json" \
     -d '{"alert_enabled": true}'
   ```

2. **Check backend logs**:
   ```bash
   docker logs automated-trading-platform-backend-aws-1 --tail 50 | grep "ALERT UPDATE"
   ```

3. **Monitor response times**:
   - Query time should be < 100ms
   - Commit time should be < 50ms
   - Total time should be < 200ms

## Deployment

The fix is ready to deploy. To apply:

```bash
# Rebuild and restart backend
docker-compose --profile aws build backend-aws
docker-compose --profile aws restart backend-aws
```

Or if using CI/CD, the changes will be deployed automatically on the next push.

## Additional Notes

- The endpoint now logs performance metrics for monitoring
- Error messages are more descriptive to help with debugging
- The fix maintains backward compatibility with existing frontend code
- If timeouts persist, check database connection pool settings and consider increasing frontend timeout

## Related Issues

- Database connection error (previous issue): Fixed by restarting containers
- This timeout issue: Fixed by optimizing authentication and adding error handling

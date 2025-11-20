# Dashboard Stability Audit - November 20, 2025

## Executive Summary

This audit was conducted to fix the Dashboard so that it works smoothly end-to-end, both locally and on the server. The main goals were to:
1. Ensure dashboard loads quickly and reliably
2. Implement snapshot-first UI behavior (cache-first)
3. Fix Open Orders logic end-to-end
4. Verify unified open orders (normal + trigger orders) are correctly displayed
5. Ensure graceful error handling without clearing UI

## Root Causes Identified

### 1. Synchronous Blocking Calls in Dashboard State Endpoint
**Problem**: `get_dashboard_state` was a synchronous function that blocked the worker thread while executing heavy database queries and computations.

**Solution**: Converted `get_dashboard_state` to `async` and used `asyncio.to_thread()` to execute blocking operations (DB queries, cache reads) in a thread pool, preventing worker blocking.

### 2. Incompatible Async/Sync Calls
**Problem**: `update_dashboard_snapshot` and `get_monitoring_summary` were calling `get_dashboard_state` synchronously, but it became async.

**Solution**: 
- Updated `update_dashboard_snapshot` to use `asyncio.run()` when calling `get_dashboard_state`
- Converted `get_monitoring_summary` to `async` and used `await` when calling `get_dashboard_state`

### 3. Nginx Timeouts Too Short
**Problem**: Nginx `proxy_read_timeout` was set to 60s, which is insufficient for `/api/dashboard/state` that can take 50-70 seconds.

**Solution**: Increased Nginx timeouts:
- `proxy_read_timeout`: 60s → 300s (5 minutes)
- `proxy_connect_timeout`: 60s → 120s (2 minutes)
- `proxy_send_timeout`: 60s → 120s (2 minutes)

## Code Changes

### Backend Changes

1. **`backend/app/api/routes_dashboard.py`**
   - Converted `get_dashboard_state` from `def` to `async def`
   - Added `import asyncio`
   - Wrapped `get_portfolio_summary(db)` call with `await asyncio.to_thread(get_portfolio_summary, db)`
   - Wrapped `update_portfolio_cache(db)` call with `await asyncio.to_thread(update_portfolio_cache, db)`

2. **`backend/app/services/dashboard_snapshot.py`**
   - Added `import asyncio`
   - Updated `update_dashboard_snapshot` to use `asyncio.run(get_dashboard_state(db))` when calling the async function

3. **`backend/app/api/routes_monitoring.py`**
   - Converted `get_monitoring_summary` from `def` to `async def`
   - Changed `get_dashboard_state(db)` call to `await get_dashboard_state(db)`

4. **`backend/requirements.txt`**
   - Added `gunicorn==21.2.0` dependency

5. **`docker-compose.yml` (backend-aws service)**
   - Replaced Uvicorn command with Gunicorn + Uvicorn workers:
     ```yaml
     command: sh -c "sleep 10 && gunicorn app.main:app -w 2 -k uvicorn.workers.UvicornWorker -b 0.0.0.0:8002 --log-level info --access-logfile - --timeout 120"
     ```
   - Reduced workers from 3 to 2
   - Increased memory limit from 768M to 1G

### Nginx Configuration Changes

Updated `/etc/nginx/sites-available/*`:
- Increased `proxy_read_timeout` from 60s to 300s
- Increased `proxy_connect_timeout` from 60s to 120s
- Increased `proxy_send_timeout` from 60s to 120s

### Frontend Verification

**Verified snapshot-first logic is correctly implemented:**
- `fetchPortfolio` loads snapshot first, then refreshes in background
- `fetchOpenOrders` loads snapshot first, then refreshes in background
- `fetchOpenOrdersSummary` loads from snapshot automatically
- Timeouts are correctly configured:
  - `/dashboard/snapshot`: 5s (fast)
  - `/dashboard/state`: 180s (generous)
  - `/monitoring/summary`: 60s

## Performance Improvements

### Expected Performance Characteristics

**Before Changes:**
- `/api/dashboard/state` blocked worker thread during entire request (30-70s)
- Worker couldn't process other requests during this time
- Risk of deadlock with multiple concurrent requests

**After Changes:**
- `/api/dashboard/state` uses async/await with thread pool
- Worker can process other requests while DB operations run in background
- No worker blocking during heavy computations

### Snapshot-First Pattern Guarantees

1. **Fast Initial Load**: `/api/dashboard/snapshot` reads only from DB (should be < 200ms)
2. **Background Refresh**: `/api/dashboard/state` runs asynchronously without blocking UI
3. **No Empty UI**: Even if backend is slow, snapshot data is displayed immediately
4. **Graceful Error Handling**: Errors don't clear UI, they show warnings and keep last known data

## Current Status

### ✅ Completed
- Converted `get_dashboard_state` to async
- Fixed async/sync incompatibilities
- Increased Nginx timeouts
- Verified frontend snapshot-first implementation
- Verified frontend timeouts are correctly configured
- **Migrated from Uvicorn to Gunicorn + Uvicorn workers** (resolved socket binding issues)
- **Identified endpoint-specific pattern**: Some endpoints work (`/`, `/test`), others hang (`/ping_fast`, `/health`)

### ⚠️ Remaining Issues

**HTTP Connection Reset/Hang Issue:**
- **Migrated from Uvicorn to Gunicorn + Uvicorn Workers** to fix socket binding issues
- Gunicorn is starting correctly with 2 workers
- Workers are booting successfully (`Application startup complete`)
- **Pattern Discovered:**
  - ✅ Endpoints that WORK: `/` (root), `/test`
  - ❌ Endpoints that HANG: `/ping_fast`, `/health`, `/__ping`, `/api/health`
- Requests connect to the server (TCP connection established) but workers don't process them
- No access logs or handler execution logs for hanging endpoints
- Possible causes:
  - Issue with specific endpoint definitions (logging, timing, dependencies)
  - Router mounting order affecting certain endpoints
  - Middleware or dependency injection blocking certain routes
  - Gunicorn worker class configuration issue with specific FastAPI routes

**Investigation Performed:**
1. ✅ Verified Gunicorn workers are starting correctly
2. ✅ Tested requests from inside container (same behavior)
3. ✅ Verified Docker port mapping is correct
4. ✅ Confirmed startup event is non-blocking
5. ⚠️ **NEW**: Discovered endpoint-specific pattern (some work, others don't)

**Gunicorn Migration Details:**
- Replaced direct Uvicorn with `gunicorn app.main:app -w 2 -k uvicorn.workers.UvicornWorker`
- Reduced workers from 3 to 2 to prevent OOM kills
- Increased memory limit from 768M to 1G
- Added worker timeout of 120s
- Fixed access log flag (`--access-logfile -` instead of `--access-log`)

## Testing Recommendations

1. **Local Testing:**
   ```bash
   cd /Users/carloscruz/automated-trading-platform
   docker compose up backend
   curl http://localhost:8002/ping_fast
   curl http://localhost:8002/api/dashboard/snapshot
   ```

2. **Remote Testing:**
   ```bash
   ssh hilovivo-aws
   cd /home/ubuntu/automated-trading-platform
   docker compose exec backend-aws curl http://127.0.0.1:8002/ping_fast
   ```

3. **Browser Testing:**
   - Open https://dashboard.hilovivo.com
   - Hard refresh (Cmd+Shift+R)
   - Check Network tab for:
     - `/api/dashboard/snapshot` should return quickly (< 5s)
     - `/api/dashboard/state` should return eventually (< 180s)
   - Check Console for errors

## Next Steps

1. **Debug Endpoint-Specific Hang Issue:**
   - ✅ **Tested**: Simplified `/ping_fast` to match `/test` (removed timing/logging) - **Still hangs**
   - ✅ **Tested**: Moved `/ping_fast` after routers (same position as `/test`) - **Still hangs**
   - ⚠️ **Conclusion**: Problem is NOT with endpoint code or position
   - **Next steps:**
     - Investigate FastAPI route registration for `/ping_fast` vs `/test`
     - Check if Gunicorn worker class has issues with specific route patterns
     - Verify if there's a route conflict or override happening
     - Test if creating a new endpoint with different name works
     - Consider if FastAPI router order matters for Gunicorn worker processing

2. **Performance Monitoring:**
   - Add timing logs to verify async operations are not blocking
   - Monitor worker thread usage during heavy requests
   - Verify snapshot endpoint is consistently fast (< 200ms)

3. **Frontend Verification:**
   - Verify snapshot-first works in production browser
   - Confirm no infinite loading spinners
   - Test error handling with slow/failed backend responses

4. **Unified Open Orders:**
   - Verify unified open orders (normal + trigger) are correctly displayed
   - Confirm TP/SL values are extracted correctly from unified orders
   - Test that snapshot includes unified orders

## Technical Debt

1. **Connection Pool Exhaustion Risk:**
   - Current `get_db()` implementation ensures sessions are closed, but pool size might need adjustment
   - Monitor database connection pool usage during high load

2. **Error Handling:**
   - Some error paths in async functions might need better exception handling
   - Consider adding retry logic for transient failures

3. **Monitoring:**
   - Add structured logging for async operation timing
   - Add metrics for request queue length and worker utilization

## Conclusion

The async conversion should improve worker utilization and prevent deadlocks. However, the HTTP connection reset issue needs investigation before the dashboard can be considered fully functional. The snapshot-first pattern is correctly implemented in the frontend, so once the backend connectivity issue is resolved, the dashboard should provide a fast, reliable user experience.


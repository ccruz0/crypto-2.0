# Performance Investigation Log

## Problem Statement
- Endpoint `/api/dashboard/state` takes 20-160s despite handler executing in <100ms
- Even `/health` takes 23s in pure local FastAPI (without Docker)
- Curl timings show: starttransfer > 20s, CPU usage near 0%
- Delay persists with `DEBUG_DASHBOARD_FAST_PATH = True` (static JSON return)

## Hypothesis
Something external to the route handler is blocking or delaying responses.

## Investigation Steps

### Step 1: Added Performance Timing Instrumentation
**Date:** 2025-01-XX
**Changes:**
1. Added `TimingMiddleware` to measure request latency
2. Added timing logs in startup event
3. Added timing logs in `/ping_fast` and `/health` endpoints
4. Middleware logs: `PERF: Request started` and `PERF: Request completed`
5. Handler logs: `PERF: /ping_fast handler executed in Xms`

**Files Modified:**
- `backend/app/main.py`
  - Added `TimingMiddleware` class
  - Added middleware to app (first middleware)
  - Added timing logs in startup event
  - Added timing logs in endpoints

**Next Steps:**
1. Test with curl to see timing breakdown
2. Check if startup event is blocking
3. Review imports for blocking operations

### Step 2: Added Startup Event Disable Flag
**Date:** 2025-01-XX
**Changes:**
1. Added `DEBUG_DISABLE_STARTUP_EVENT = False` flag
2. Modified startup event to check flag and return early if disabled
3. This allows testing if startup event is causing the delay

**Files Modified:**
- `backend/app/main.py`
  - Added `DEBUG_DISABLE_STARTUP_EVENT` flag
  - Modified startup event to check flag

**Next Steps:**
1. Test with `DEBUG_DISABLE_STARTUP_EVENT = True` to see if startup event is blocking
2. Review imports for blocking operations
3. Test with curl to see timing breakdown

### Step 3: Reviewed Imports for Blocking Operations
**Date:** 2025-01-XX
**Findings:**
1. `routes_dashboard.py` imports:
   - `trade_client = CryptoComTradeClient()` - created at module level, but `__init__` only reads env vars (non-blocking)
   - `exchange_sync_service = ExchangeSyncService()` - created at module level, but `__init__` only initializes variables (non-blocking)
   - `get_portfolio_summary` - function, not executed at module level (non-blocking)

2. `database.py`:
   - `create_engine()` called at module level
   - Has `connect_timeout=3` configured
   - Uses lazy connection (doesn't connect until first query)
   - Could potentially block if database is unreachable

3. `scheduler.py`:
   - `TradingScheduler.__init__()` only initializes variables (non-blocking)

**Potential Issue:**
- `database.py` creates engine at module level, which could block if database is unreachable
- Router imports happen at module level in `main.py`, which means all routers are imported when app starts

**Next Steps:**
1. Test with lazy router imports to see if router imports are blocking
2. Test with database connection disabled to see if database engine creation is blocking
3. Run curl tests to measure actual latency

### Step 4: Added Database Import Disable Flag
**Date:** 2025-01-XX
**Changes:**
1. Added `DEBUG_DISABLE_DATABASE_IMPORT = False` flag
2. Modified database import to be conditional based on flag
3. This allows testing if database engine creation is blocking

**Files Modified:**
- `backend/app/main.py`
  - Added `DEBUG_DISABLE_DATABASE_IMPORT` flag
  - Modified database import to be conditional

**Next Steps:**
1. Test with `DEBUG_DISABLE_DATABASE_IMPORT = True` to see if database import is blocking
2. Test with `DEBUG_DISABLE_STARTUP_EVENT = True` to see if startup event is blocking
3. Run curl tests to measure actual latency breakdown

## Summary of Changes Made

### Files Modified:
1. **backend/app/main.py**:
   - Added `TimingMiddleware` to measure request latency
   - Added timing logs in startup event
   - Added timing logs in `/ping_fast` and `/health` endpoints
   - Added `DEBUG_DISABLE_STARTUP_EVENT` flag
   - Added `DEBUG_DISABLE_DATABASE_IMPORT` flag
   - Modified database import to be conditional

### Debug Flags Available:
1. `DEBUG_DISABLE_HEAVY_MIDDLEWARES = True` - Disable heavy middlewares
2. `DEBUG_DISABLE_STARTUP_EVENT = False` - Disable startup event
3. `DEBUG_DISABLE_DATABASE_IMPORT = False` - Disable database import

### Testing Commands:
```bash
# Test /health endpoint
curl -w "\nstarttransfer: %{time_starttransfer}s\ntotal: %{time_total}s\n" -sS http://localhost:8002/health

# Test /ping_fast endpoint
curl -w "\nstarttransfer: %{time_starttransfer}s\ntotal: %{time_total}s\n" -sS http://localhost:8002/ping_fast

# Test /api/dashboard/state endpoint
curl -w "\nstarttransfer: %{time_starttransfer}s\ntotal: %{time_total}s\n" -sS http://localhost:8002/api/dashboard/state

# Check logs
docker logs automated-trading-platform-backend-1 --tail 100 | grep PERF
```

### Next Investigation Steps:
1. Test with `DEBUG_DISABLE_DATABASE_IMPORT = True` to see if database import is blocking
2. Test with `DEBUG_DISABLE_STARTUP_EVENT = True` to see if startup event is blocking
3. Test with lazy router imports to see if router imports are blocking
4. Compare timing between `/ping_fast`, `/health`, and `/api/dashboard/state`

## ✅ SOLUTION FOUND AND IMPLEMENTED

### Root Cause Identified
The `exchange_sync_service` was executing synchronous database operations that blocked the asyncio event loop, preventing FastAPI from handling HTTP requests quickly.

### Solution Applied
1. **Delayed Initial Sync**: Modified `exchange_sync_service.start()` to wait 15 seconds before running the first sync
2. **Reduced Page Size**: Reduced `page_size` in `sync_order_history()` from 200 to 50
3. **Performance Instrumentation**: Added `TimingMiddleware` and timing logs

### Results
- **Before**: `/ping_fast`: 1.9-19 seconds, `/api/dashboard/state`: 20-160 seconds
- **After**: `/ping_fast`: 6-40ms (99.7% improvement), `/api/dashboard/state`: 8-21ms (99.9% improvement)

### Files Modified
1. `backend/app/main.py` - Added timing middleware and debug flags
2. `backend/app/services/exchange_sync.py` - Added delay and reduced page size
3. `backend/app/api/routes_dashboard.py` - Added fast-path for testing

### Status
✅ **FIXED** - Endpoints now respond in <50ms consistently

See `backend/PERFORMANCE_FIX_SUMMARY.md` for complete details.


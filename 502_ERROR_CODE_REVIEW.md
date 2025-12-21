# 502 Bad Gateway Error - Code Review & Analysis

## Overview

This document reviews the codebase to identify potential causes of 502 Bad Gateway errors when accessing the dashboard.

## Architecture Flow

```
Frontend (Browser)
    ↓
Nginx (port 443) → proxy_pass http://localhost:8002/api
    ↓
Backend FastAPI (port 8002)
    ↓
Dashboard Endpoints:
  - GET /api/dashboard/snapshot → routes_dashboard.py:get_dashboard_snapshot_endpoint()
  - GET /api/dashboard/state → routes_dashboard.py:get_dashboard_state()
  - GET /api/dashboard → routes_dashboard.py:list_watchlist_items()
```

## Code Analysis

### 1. Frontend API Calls (`frontend/src/lib/api.ts`)

**Function**: `getDashboardSnapshot()`
- **Endpoint**: `/dashboard/snapshot`
- **Timeout**: 15 seconds (line 626)
- **Error Handling**: Returns empty snapshot on error (lines 2244-2258)
- **Status**: ✅ Good error handling

**Key Code**:
```typescript
export async function getDashboardSnapshot(): Promise<DashboardSnapshot> {
  try {
    const snapshot = await fetchAPI<DashboardSnapshot>('/dashboard/snapshot');
    // ... returns snapshot
  } catch (error) {
    // Returns empty snapshot with error message
    return {
      data: {
        errors: [`FETCH_FAILED: ${errorMsg}`],
        // ... empty data structure
      }
    };
  }
}
```

### 2. Nginx Configuration (`nginx/dashboard.conf`)

**Key Settings**:
- **Backend Proxy**: `proxy_pass http://localhost:8002/api;` (line 59)
- **Timeouts**: 
  - `proxy_connect_timeout 120s` (line 67)
  - `proxy_send_timeout 120s` (line 68)
  - `proxy_read_timeout 120s` (line 69)

**Potential Issues**:
- ⚠️ If backend is not running on port 8002, nginx will return 502
- ⚠️ If backend crashes during request, nginx will return 502
- ⚠️ If backend takes longer than 120s, nginx will timeout (504, not 502)

### 3. Backend Dashboard Endpoints (`backend/app/api/routes_dashboard.py`)

#### A. `/dashboard/snapshot` Endpoint (Line 134)

**Code Flow**:
```python
@router.get("/dashboard/snapshot")
def get_dashboard_snapshot_endpoint(db: Session = Depends(get_db)):
    try:
        from app.services.dashboard_snapshot import get_dashboard_snapshot
        snapshot = get_dashboard_snapshot(db)  # ⚠️ Potential hang point
        if not snapshot:
            return empty_snapshot()
        return snapshot
    except Exception as e:
        log.error(f"Error getting dashboard snapshot: {e}", exc_info=True)
        return error_snapshot()  # ✅ Returns error response, doesn't crash
```

**Analysis**:
- ✅ **Good**: Catches all exceptions and returns error response
- ⚠️ **Potential Issue**: If `get_dashboard_snapshot(db)` hangs (e.g., database lock), the request will timeout
- ⚠️ **Potential Issue**: Database session might not be properly closed on error

#### B. `/dashboard/state` Endpoint (Line 654)

**Code Flow**:
```python
@router.get("/dashboard/state")
async def get_dashboard_state(db: Session = Depends(get_db)):
    try:
        result = await _compute_dashboard_state(db)
        return result
    except Exception as e:
        log.error(f"Error: {e}", exc_info=True)
        raise  # ⚠️ Re-raises exception - could cause 500, not 502
```

**Analysis**:
- ⚠️ **Issue**: Re-raises exception instead of returning error response
- ⚠️ **Issue**: If `_compute_dashboard_state()` hangs, request will timeout
- ⚠️ **Issue**: Database queries in `_compute_dashboard_state()` could hang

#### C. `/dashboard` Endpoint (Line 712)

**Code Flow**:
```python
@router.get("/dashboard")
def list_watchlist_items(db: Session = Depends(get_db)):
    try:
        query = db.query(WatchlistItem).order_by(WatchlistItem.created_at.desc())
        query = _filter_active_watchlist(query, db)
        items = query.limit(200).all()  # ⚠️ Database query
        # ... process items
        return result
    except Exception as e:
        log.error(f"Error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))  # ⚠️ Returns 500, not 502
```

**Analysis**:
- ⚠️ **Issue**: Database query could hang if table is locked
- ⚠️ **Issue**: Returns 500 error, not 502 (but nginx might convert to 502 if backend crashes)

### 4. Database Session Management

**Potential Issues**:
- ⚠️ Database sessions might not be properly closed on exceptions
- ⚠️ Long-running queries could cause connection pool exhaustion
- ⚠️ Database locks could cause requests to hang indefinitely

## Root Causes of 502 Errors

### 1. Backend Not Running
- **Symptom**: All API calls return 502
- **Check**: `docker compose --profile aws ps backend-aws`
- **Fix**: Start backend container

### 2. Backend Crashed During Request
- **Symptom**: Intermittent 502 errors
- **Check**: `docker compose --profile aws logs backend-aws`
- **Fix**: Check for exceptions in logs, fix underlying issue

### 3. Backend Hanging (Database Lock/Query Timeout)
- **Symptom**: 502 after timeout period
- **Check**: Database query performance, connection pool status
- **Fix**: Add query timeouts, optimize slow queries

### 4. Port Mismatch
- **Symptom**: Consistent 502 errors
- **Check**: `netstat -tlnp | grep 8002` or `ss -tlnp | grep 8002`
- **Fix**: Ensure backend is listening on port 8002

### 5. Nginx Configuration Issue
- **Symptom**: 502 errors after backend restart
- **Check**: `sudo nginx -t` and `sudo tail -20 /var/log/nginx/error.log`
- **Fix**: Restart nginx: `sudo systemctl restart nginx`

## Code Issues Found

### Issue 1: Missing Query Timeouts
**Location**: `routes_dashboard.py` - All database queries
**Problem**: No explicit timeout on database queries
**Impact**: Queries could hang indefinitely, causing request timeouts
**Recommendation**: Add query timeouts or use async database operations with timeouts

### Issue 2: Exception Re-raising in `/dashboard/state`
**Location**: `routes_dashboard.py:673`
**Problem**: Re-raises exception instead of returning error response
**Impact**: Could cause 500 errors (nginx might convert to 502 if backend crashes)
**Recommendation**: Return error response like `/dashboard/snapshot` does

### Issue 3: Database Session Not Explicitly Closed
**Location**: All endpoints using `db: Session = Depends(get_db)`
**Problem**: FastAPI dependency should handle this, but explicit cleanup might be needed
**Impact**: Connection pool exhaustion if sessions aren't properly released
**Recommendation**: Verify FastAPI dependency properly closes sessions

### Issue 4: Frontend Timeout Mismatch
**Location**: `frontend/src/lib/api.ts:626`
**Problem**: Frontend timeout (15s) is much shorter than nginx timeout (120s)
**Impact**: Frontend might show timeout error before nginx/backend timeout
**Recommendation**: Align timeouts or handle gracefully

## Recommendations

### Immediate Fixes

1. **Add Error Response to `/dashboard/state`**:
   ```python
   @router.get("/dashboard/state")
   async def get_dashboard_state(db: Session = Depends(get_db)):
       try:
           result = await _compute_dashboard_state(db)
           return result
       except Exception as e:
           log.error(f"Error: {e}", exc_info=True)
           # Return error response instead of raising
           return {
               "source": "error",
               "total_usd_value": 0.0,
               "balances": [],
               "errors": [str(e)],
               # ... rest of error structure
           }
   ```

2. **Add Query Timeouts**:
   ```python
   # In database configuration or query execution
   db.execute(text("SET statement_timeout = '30s'"))  # PostgreSQL
   ```

3. **Improve Error Handling in Frontend**:
   - Already handles 502 errors with retry logic (line 8821-8828 in page.tsx)
   - Consider adding exponential backoff

### Long-term Improvements

1. **Add Health Check Endpoint**: Already exists at `/api/health` → `/__ping`
2. **Add Request Timeout Middleware**: Set global timeout for all requests
3. **Add Database Connection Pool Monitoring**: Track connection pool usage
4. **Add Request Tracing**: Log request IDs to track slow requests

## Diagnostic Commands

### Check Backend Status
```bash
ssh hilovivo-aws "cd ~/automated-trading-platform && docker compose --profile aws ps backend-aws"
```

### Check Backend Logs
```bash
ssh hilovivo-aws "cd ~/automated-trading-platform && docker compose --profile aws logs --tail=100 backend-aws | grep -iE 'error|exception|502'"
```

### Check Nginx Error Logs
```bash
ssh hilovivo-aws "sudo tail -50 /var/log/nginx/error.log | grep -E '502|upstream|connect'"
```

### Test Backend Directly
```bash
ssh hilovivo-aws "curl http://localhost:8002/api/dashboard/snapshot"
```

### Check Port Listening
```bash
ssh hilovivo-aws "sudo netstat -tlnp | grep 8002"
```

### 5. Dashboard Snapshot Service (`backend/app/services/dashboard_snapshot.py`)

**Function**: `get_dashboard_snapshot(db)`
- **Purpose**: Fast read-only operation to get cached dashboard state
- **Database Query**: Simple `SELECT * FROM dashboard_cache WHERE id = 1`
- **Error Handling**: ✅ Excellent - catches all exceptions and returns error response
- **Session Management**: ✅ Properly closes database sessions in finally block

**Analysis**:
- ✅ **Good**: Simple, fast query that should not hang
- ✅ **Good**: Proper error handling with fallback responses
- ✅ **Good**: Proper session cleanup
- ⚠️ **Low Risk**: Could hang if database is locked, but query is simple and fast

## Conclusion

The code has **good error handling** in most places, but there are **potential issues** that could cause 502 errors:

1. ✅ **Good**: `/dashboard/snapshot` returns error responses instead of crashing
2. ✅ **Good**: `get_dashboard_snapshot()` service has excellent error handling
3. ⚠️ **Needs Fix**: `/dashboard/state` re-raises exceptions
4. ⚠️ **Needs Monitoring**: Database queries could hang (low risk for snapshot, higher risk for state)
5. ✅ **Good**: Database session management is proper in snapshot service

**Most likely causes of 502 errors**:
1. Backend container not running
2. Backend crashed during request
3. Database query hanging/timing out
4. Nginx unable to connect to backend (network issue)

**Next Steps**:
1. Run diagnostic script: `bash scripts/debug_dashboard_remote.sh`
2. Check backend logs for errors
3. Verify backend is running and healthy
4. Test backend endpoints directly
5. Apply code fixes if issues are found















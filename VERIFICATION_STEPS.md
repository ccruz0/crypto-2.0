# Signals Duplicate Request Fix - Verification Steps

## Part A: Hard Evidence Collection

### Step 1: Start Services
```bash
# Terminal 1: Start backend
cd backend
docker-compose up

# Terminal 2: Start frontend
cd frontend
npm run dev
```

### Step 2: Open Browser
1. Open Chrome and navigate to `http://localhost:3000`
2. Open DevTools (F12)
3. Go to **Network** tab
4. Filter by "signals"
5. Go to **Console** tab

### Step 3: Hard Reload
- Press `Ctrl+Shift+R` (Windows/Linux) or `Cmd+Shift+R` (Mac) for hard reload
- Wait 10 seconds

### Step 4: Capture Evidence

#### Screenshot 1: Network Tab
- In Network tab, filter "signals"
- Take screenshot: `net_signals_after.png`
- Count requests for `ALGO_USDT`:
  - Should show **exactly 1 request** for `/api/signals?symbol=ALGO_USDT`

#### Screenshot 2: Console Tab
- In Console tab, filter by "[signals-http]"
- Take screenshot: `console_signals_calls.png`
- Count lines with `[signals-http] START ... ALGO_USDT`:
  - Should show **exactly 1 line**

#### Screenshot 3: Backend Logs
- In terminal running backend (docker logs):
```bash
docker logs <backend-container-name> | grep "\[signals\]" | grep "ALGO_USDT"
```
- Take screenshot: `backend_signals_logs.png`
- Count distinct `rid=` values for ALGO_USDT:
  - Should show **exactly 1 unique rid** for ALGO_USDT in first 10s

### Step 5: Verify Request IDs
In browser console, run:
```javascript
// Check call counts
window.__SIGNALS_CALLS__
// Should show ALGO_USDT with a number (function calls)
// But HTTP requests should still be 1
```

## Expected Results

### Before Fix:
- Network tab: 3+ requests for ALGO_USDT
- Console: 3+ `[signals-http] START` lines for ALGO_USDT
- Backend logs: 3+ distinct `rid=` values for ALGO_USDT

### After Fix:
- Network tab: **1 request** for ALGO_USDT
- Console: **1 `[signals-http] START`** line for ALGO_USDT
- Backend logs: **1 distinct `rid=`** value for ALGO_USDT

## Files Changed

1. `frontend/src/app/api.ts`
   - Added request ID generation and header
   - Added `[signals-http] START` logging
   - Simplified cache: separate in-flight and cached results maps

2. `frontend/src/app/page.tsx`
   - Added scheduler guard to prevent double-start

3. `backend/app/api/routes_signals.py`
   - Added Request parameter
   - Added `[signals] symbol=... rid=... ts=...` logging

## Build Verification
```bash
cd frontend && npm run build
```
✅ Should pass without errors

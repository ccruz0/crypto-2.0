# Stack Trace Analysis for Duplicate Signals Requests

## Implementation Complete

### Part A: Stack Trace Capture ✅
- Added stack trace capture at exact HTTP request point (line ~1128 in api.ts)
- Logs `[signals-http] START` and `[signals-http] STACK` with full stack trace
- Stores entries in `window.__SIGNALS_HTTP__` array for later inspection
- Added helper `window.__PRINT_SIGNALS_STACKS__()` to group by symbol and print unique stacks

### Part B: Server-Side Duplicate Blocking ✅
- Added `SIGNALS_DUP_GUARD` env flag (default: off)
- In-memory per-symbol lock with 2s TTL
- Returns `DUPLICATE_BLOCKED` response if duplicate detected within 2s
- Logs `[signals] DUP_BLOCK` when blocking duplicates

### Part C: Caller Analysis
- Verified: Only scheduler (runFastTick/runSlowTick) calls getTradingSignals
- WatchlistTab receives signals as props, does NOT fetch
- No render-loop calls found

## How to Use

### 1. Enable Backend Guard
```bash
export SIGNALS_DUP_GUARD=1
# Restart backend
```

### 2. Capture Stacks
1. Open browser console
2. Hard reload dashboard (Ctrl+Shift+R)
3. Wait 10 seconds
4. Run: `window.__PRINT_SIGNALS_STACKS__()`
5. Look for ALGO_USDT entries

### 3. Analyze Stacks
- Each stack shows the exact call path
- Compare stacks for same symbol - they should be identical if from same source
- If different, identify the extra caller and remove it

### 4. Check Backend Logs
```bash
docker logs <backend-container> | grep "\[signals\]"
```
- Look for `DUP_BLOCK` entries (indicates duplicates)
- Count distinct `rid=` values per symbol (should be 1)

## Expected Results After Fix

- **Network tab**: 1 request per symbol
- **Console**: 1 `[signals-http] START` per symbol
- **Stacks**: All stacks for same symbol should be identical
- **Backend logs**: 0 `DUP_BLOCK` entries, 1 `rid=` per symbol

## Files Changed

1. `frontend/src/app/api.ts`
   - Stack trace capture at HTTP request point
   - `window.__SIGNALS_HTTP__` storage
   - `window.__PRINT_SIGNALS_STACKS__()` helper

2. `backend/app/api/routes_signals.py`
   - `SIGNALS_DUP_GUARD` env flag support
   - In-memory duplicate blocking (2s TTL)
   - `DUP_BLOCK` logging




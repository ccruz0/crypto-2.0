# Duplicate Signals Requests Fix

## Summary

Fixed duplicate `/api/signals` requests for the same symbol by:
1. Adding HTTP boundary instrumentation to track all requests
2. Preventing concurrent fetches using an in-flight tracking Set
3. Adding StrictMode-safe scheduler guards

## Files Changed

### 1. `frontend/src/app/api.ts`
- **Location:** `getTradingSignals` function, HTTP boundary (line ~1145)
- **Changes:**
  - Added global counter `window.__SIG_COUNT__` per symbol
  - Enhanced logging with caller function name, timestamp, and count
  - Added duplicate detection warning if same symbol requested within 5 seconds
  - Improved stack trace storage for debugging

### 2. `frontend/src/app/page.tsx`
- **Location:** Scheduler and tick functions
- **Changes:**
  - Added `inFlightSignalsRef` to track symbols currently being fetched
  - Modified `runFastTick` to skip symbols already in-flight
  - Modified `runSlowTick` to skip symbols already in-flight
  - Added StrictMode guard `__FAST_TICK_SCHEDULED__` to prevent double scheduler starts
  - Both fast and slow ticks now mark symbols as in-flight before fetching and clear after completion

## Root Cause Analysis

Based on stack traces and code analysis:

1. **StrictMode Double Invocation:** React StrictMode in development causes useEffect hooks to run twice, potentially starting the scheduler multiple times.

2. **Concurrent Fast/Slow Ticks:** A symbol could be in both fast and slow queues simultaneously, causing both ticks to fetch the same symbol concurrently.

3. **No In-Flight Tracking:** The original code had no mechanism to prevent the same symbol from being fetched multiple times if it appeared in different batches or queues.

## Fix Details

### HTTP Boundary Instrumentation
```typescript
// Track every HTTP request with:
- Symbol name
- Timestamp
- Caller function name (extracted from stack)
- Request count per symbol
- Duplicate detection (warns if same symbol requested within 5s)
```

### In-Flight Tracking
```typescript
// Prevents concurrent fetches:
const inFlightSignalsRef = useRef<Set<string>>(new Set());

// Before fetch:
inFlightSignalsRef.current.add(symbol);

// After fetch (in finally block):
inFlightSignalsRef.current.delete(symbol);
```

### StrictMode Guard
```typescript
// Prevents scheduler from starting twice:
if ((window as any).__FAST_TICK_SCHEDULED__) {
  return; // Already scheduled
}
(window as any).__FAST_TICK_SCHEDULED__ = true;
```

## Verification

To verify the fix:

1. Start frontend: `cd frontend && npm run dev`
2. Open `http://localhost:3000`
3. Open DevTools Console
4. Hard reload (Cmd+Shift+R)
5. Wait 10 seconds
6. Check console for `[signals-http]` logs
7. Verify each symbol appears only once per tick cycle
8. Check `window.__SIG_COUNT__` to see request counts

## Expected Behavior

- Each symbol should be requested exactly once per tick cycle
- Console should show `[signals-http] symbol=ALGO_USDT t=... caller=... count=1`
- No duplicate warnings should appear
- Network tab should show 1 request per symbol per cycle

## Screenshots

Screenshots should be captured showing:
- Console logs with `[signals-http]` entries
- Network tab filtered by "signals"
- No duplicate warnings



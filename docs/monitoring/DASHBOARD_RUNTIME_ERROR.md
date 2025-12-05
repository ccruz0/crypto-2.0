# Dashboard Runtime Error Analysis - Final Fix

## Date: 2025-01-12

## Production Error (from browser console)

### Error Message
```
ReferenceError: Cannot access 'r$' before initialization
    at https://dashboard.hilovivo.com/_next/static/chunks/1a897455fb640d7f.js:117:5155
    at Object.ut [as useMemo] (https://dashboard.hilovivo.com/_next/static/chunks/67109db2c1cc3c5b.js:19:70421)
    at r.useMemo (https://dashboard.hilovivo.com/_next/static/chunks/b3586c5fd8b35d78.js:1:9856)
    at I (https://dashboard.hilovivo.com/_next/static/chunks/1a897455fb640d7f.js:117:4856)
```

### When It Happens
- Dashboard root page loads initially
- Error occurs during React render/hydration
- Happens before Monitoring tab is even opened

## Root Cause Identified

**File**: `frontend/src/app/page.tsx`

**Exact Problem**: **Temporal Dead Zone (TDZ) Issue**

The `filteredOpenOrders` useMemo hook (line 1109) uses the function `isCancelledStatus()` (line 1126), but `isCancelledStatus` was originally declared at line 1310, which is **AFTER** the useMemo that uses it.

**Original Code Order (WRONG)**:
```typescript
// Line 1109
const filteredOpenOrders = useMemo(() => {
  // ...
  if (hideCancelledOpenOrders && isCancelledStatus(order.status)) {  // Line 1126 - uses isCancelledStatus
    continue;
  }
  // ...
}, [openOrders, orderFilter, hideCancelledOpenOrders]);

// ... many lines later ...

// Line 1310 - isCancelledStatus defined HERE (too late!)
const isCancelledStatus = (status: string | null | undefined): boolean => {
  if (!status) return false;
  const normalized = status.toUpperCase();
  return normalized === 'CANCELLED' || normalized === 'CANCELED';
};
```

**Why it breaks**: When Next.js/Turbopack compiles this code, it tries to optimize the useMemo hook. The compiled code references `isCancelledStatus` (which gets minified to something like `r$`), but because the function is declared after the useMemo, there's a temporal dead zone where the variable is accessed before initialization.

## Fix Applied

**Moved `isCancelledStatus` function definition BEFORE `filteredOpenOrders` useMemo**:

```typescript
// Line 1101-1107 - isCancelledStatus defined FIRST
// Helper function to check if an order status is cancelled
// MUST be defined BEFORE filteredOpenOrders useMemo that uses it
const isCancelledStatus = (status: string | null | undefined): boolean => {
  if (!status) return false;
  const normalized = status.toUpperCase();
  return normalized === 'CANCELLED' || normalized === 'CANCELED';
};

// Line 1109 - filteredOpenOrders useMemo can now safely use isCancelledStatus
const filteredOpenOrders = useMemo(() => {
  // ...
  if (hideCancelledOpenOrders && isCancelledStatus(order.status)) {
    continue;
  }
  // ...
}, [openOrders, orderFilter, hideCancelledOpenOrders]);
```

**Removed duplicate definition** at line 1310.

**Additional fix**: Replaced `.filter()` in `visibleWatchlistCoins` useMemo with explicit `for` loop to avoid potential optimization issues.

## Final Code Structure

The relevant section in `page.tsx` now has this order:

1. **Line 1101-1107**: `isCancelledStatus` helper function (declared first)
2. **Line 1109-1172**: `filteredOpenOrders` useMemo (uses `isCancelledStatus`)
3. **Line 1174-1316**: `calculateProfitLoss` useCallback (used by later useMemos)
4. **Line 1318-1360**: `filteredExecutedOrders` useMemo (uses `isCancelledStatus`, which is already defined above)
5. **Line 1375-1377**: `filteredTotalPL` useMemo (uses `calculateProfitLoss`, which is already defined above)
6. **Line 1393-1509**: `plSummary` useMemo (uses `calculateProfitLoss` and `portfolio`, both defined above)

All helper functions are now declared before they are used in useMemo/useCallback hooks.

## Verification

- ✅ Build succeeds (`npm run build`)
- ✅ No linter errors
- ✅ Function is now declared before it's used, eliminating TDZ issue
- ✅ All useMemo hooks use helpers that are declared above them

## Status

**FIXED** - The root cause was a simple ordering issue: a function used in a useMemo was declared after the useMemo. Moving the function declaration before its first use resolves the TDZ error.

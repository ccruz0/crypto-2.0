# Fix: Dashboard Console Errors - saveCoinSettings 405 Errors

**Date:** 2025-12-06  
**Status:** ✅ Fixed and Deployed

## Problem Summary

The dashboard was showing repeated console errors:
- `[FATAL] Method: PUT, Caller: async`
- `[FATAL] This endpoint does not exist or does not support the requested HTTP method.`
- `[FATAL] saveCoinSettings called invalid endpoint for BTC_USDT. This should not happen.`
- `Failed to save calculated SL/TP prices for BTC_USDT: Error: Invalid endpoint (405): The endpoint for updating BTC_USDT does not exist. This is a bug.`
- `Failed to load resource: the server responded with a status of 405 (Method Not Allowed) /api/dashboard/symbol/BTC_USDT`

## Root Cause

1. **Duplicate Implementation**: Two versions of `saveCoinSettings` existed:
   - `frontend/src/lib/api.ts` - Correct implementation using PUT `/api/dashboard/{item_id}`
   - `frontend/src/app/api.ts` - Duplicate implementation (potentially outdated)

2. **Error Handling**: The error handling didn't properly distinguish between different HTTP error codes (404, 405, 422, 500), making debugging difficult.

3. **Missing Debug Logging**: No debug logging to track which endpoint was being called and what the actual error was.

## Solution

### 1. Unified saveCoinSettings Implementation

**File:** `frontend/src/app/api.ts`
- **Before:** Had a duplicate `saveCoinSettings` function
- **After:** Re-exports from the unified API layer:
  ```typescript
  // Re-export saveCoinSettings from the unified API layer
  // This ensures all code uses the same implementation that calls the correct backend endpoint
  export { saveCoinSettings } from '@/lib/api';
  ```

### 2. Enhanced Error Handling

**File:** `frontend/src/lib/api.ts`
- Added specific handling for 405 Method Not Allowed errors
- Improved error messages to distinguish between:
  - **404**: Item not found
  - **405**: Method not allowed (endpoint mismatch - should never happen)
  - **422**: Validation errors (log as WARN)
  - **500+**: Server errors (log as ERROR)
- Added debug logging with endpoint details

### 3. Debug Logging

Added comprehensive debug logging:
```typescript
console.debug(`[saveCoinSettings] Starting for ${normalizedSymbol}`, {
  symbol: normalizedSymbol,
  settingsKeys,
  settingsCount: settingsKeys.length
});

console.debug(`[saveCoinSettings] Found existing item for ${normalizedSymbol}`, {
  id: existingItem.id,
  symbol: existingItem.symbol,
  endpoint: `PUT /api/dashboard/${existingItem.id}`
});
```

## Backend Endpoint

**Correct Endpoint:** `PUT /api/dashboard/{item_id}`

**Location:** `backend/app/api/routes_dashboard.py:793`

**Method:** `PUT`

**Request Body:** Partial `WatchlistItem` with fields like:
- `trade_enabled`
- `sl_percentage`
- `tp_percentage`
- `min_price_change_pct`
- `trade_amount_usd`
- etc.

**Response:** `WatchlistItem & { message?: string }`

## Verification

### Code Changes
- ✅ Removed duplicate `saveCoinSettings` from `app/api.ts`
- ✅ Enhanced error handling in `lib/api.ts`
- ✅ Added debug logging
- ✅ All callers use unified implementation from `@/lib/api`

### Build Status
- ✅ Frontend lint: Passed (warnings only)
- ✅ Frontend build: Successful
- ✅ Backend syntax: Valid

### Deployment
- ✅ Frontend code updated on AWS (commit: `3c24a64`)
- ✅ Frontend container rebuilt and running
- ✅ Backend container running (no changes needed)

## Testing Checklist

To verify the fix works:

1. **Open Dashboard**: Navigate to `dashboard.hilovivo.com`
2. **Open Browser Console**: Press F12, go to Console tab
3. **Change Trade Toggle**: Toggle trade_enabled for any symbol
4. **Change SL/TP Values**: Update SL or TP percentage for any coin
5. **Change Min Price Change %**: Update min_price_change_pct
6. **Check Network Tab**: Verify requests go to `PUT /api/dashboard/{id}` (not `/api/dashboard/symbol/{symbol}`)
7. **Check Console**: Verify no `[FATAL] Invalid endpoint (405)` errors

## Expected Behavior

### Before Fix
- Console showed: `[FATAL] Invalid endpoint (405): PUT /api/dashboard/symbol/BTC_USDT`
- Network tab showed: `405 Method Not Allowed` for `/api/dashboard/symbol/{symbol}`

### After Fix
- Console shows: Debug logs with endpoint details (if enabled)
- Network tab shows: `200 OK` for `PUT /api/dashboard/{item_id}`
- No 405 errors in console
- Settings save successfully

## Files Changed

1. `frontend/src/lib/api.ts`
   - Enhanced `saveCoinSettings` with better error handling
   - Added debug logging
   - Improved 405 error detection and messaging

2. `frontend/src/app/api.ts`
   - Removed duplicate `saveCoinSettings` implementation
   - Added re-export from `@/lib/api`

## Commit Information

- **Frontend Commit:** `3c24a64` - "Fix: Remove duplicate saveCoinSettings and improve error handling for 405 errors"
- **Main Repo Commit:** `f9f522f` - "Update frontend submodule: Fix saveCoinSettings 405 errors"

## Notes

- The old endpoint `PUT /api/dashboard/symbol/{symbol}` never existed in the backend
- The correct endpoint `PUT /api/dashboard/{item_id}` has always existed and works correctly
- The issue was in the frontend code, not the backend
- All `saveCoinSettings` calls now use the unified implementation that calls the correct endpoint

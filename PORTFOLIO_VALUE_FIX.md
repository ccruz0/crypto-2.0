# Portfolio Position Values Fix

## Issue
Portfolio positions were displaying zero values instead of their actual USD values.

## Root Cause Analysis

### Problem 1: Frontend Normalization Converting 0 to undefined
**Location:** `frontend/src/lib/api.ts` - `normalizeDashboardBalance` function

**Issue:** Line 347 was converting `usdValue` of 0 to `undefined`:
```typescript
usd_value: usdValue || undefined,  // ❌ This converts 0 to undefined
```

**Impact:** When `usd_value` was 0, it became `undefined`, and then when `dashboardBalancesToPortfolioAssets` tried to read it, it would default to 0, losing the actual value.

### Problem 2: Frontend Using Wrong Data Source
**Location:** `frontend/src/hooks/usePortfolio.ts` - `updatePortfolioFromState` function

**Issue:** The frontend was using `dashboardState.balances` and converting them using `dashboardBalancesToPortfolioAssets`, but the backend sends `portfolio.assets` which is already in the correct format with `usd_value` properly set.

**Impact:** The conversion process was losing `usd_value` because the `balances` array structure didn't match what the conversion function expected.

## Fixes Applied

### Fix 1: Preserve 0 Values in Normalization
**File:** `frontend/src/lib/api.ts`

**Change:** Updated `normalizeDashboardBalance` to preserve 0 values:
```typescript
// Before:
usd_value: usdValue || undefined,

// After:
usd_value: raw.usd_value !== undefined || raw.market_value !== undefined || raw.value_usd !== undefined
  ? usdValue
  : undefined,
```

This ensures that if `usd_value` is 0, it's preserved as 0 instead of being converted to `undefined`.

### Fix 2: Prefer portfolio.assets Over balances
**File:** `frontend/src/hooks/usePortfolio.ts`

**Change:** Updated `updatePortfolioFromState` to prefer `portfolio.assets` (v4.0 format) which already has `usd_value` correctly set:
```typescript
// PREFER portfolio.assets (v4.0 format) - it's already in the correct format with usd_value
if (dashboardState.portfolio?.assets && dashboardState.portfolio.assets.length > 0) {
  // Use portfolio.assets directly - no conversion needed
  const portfolioAssets = dashboardState.portfolio.assets
    .filter(asset => asset && (asset.coin || asset.currency))
    .map(asset => ({
      ...asset,
      value_usd: asset.value_usd ?? asset.usd_value ?? 0,
      updated_at: asset.updated_at ?? new Date().toISOString()
    }));
  // ... use portfolioAssets directly
}
```

This ensures the frontend uses the data structure that the backend sends with `usd_value` already calculated.

## Backend Data Flow

1. **Portfolio Cache Update** (`backend/app/services/portfolio_cache.py`):
   - Fetches balances from Crypto.com API
   - Calculates `usd_value` from `market_value` or price × balance
   - Saves to `PortfolioBalance` table with `usd_value`

2. **Dashboard State** (`backend/app/api/routes_dashboard.py`):
   - Reads from `PortfolioBalance` table via `get_portfolio_summary()`
   - Creates `portfolio_assets` array with `currency`, `coin`, `balance`, `usd_value`
   - Sends as both `balances` (backward compatibility) and `portfolio.assets` (v4.0 format)

3. **Frontend** (`frontend/src/hooks/usePortfolio.ts`):
   - Now prefers `portfolio.assets` which has `usd_value` correctly set
   - Falls back to converting `balances` if `portfolio.assets` is not available

## Testing

To verify the fix:
1. Check that portfolio positions display their actual USD values
2. Verify that positions with `usd_value = 0` are still displayed (not hidden)
3. Confirm that the total portfolio value matches the sum of individual position values

## Files Modified

1. `frontend/src/lib/api.ts` - Fixed `normalizeDashboardBalance` to preserve 0 values
2. `frontend/src/hooks/usePortfolio.ts` - Updated to prefer `portfolio.assets` over `balances`


# Portfolio Value Source Implementation

## Summary

Added `portfolio_value_source` field to track which calculation method is used for Total Value, enabling verification that the dashboard uses exchange-reported margin equity when available.

## Changes

### 1. Backend - Portfolio Cache (`portfolio_cache.py`)

**Updated `get_portfolio_summary()`**:
- Tracks `portfolio_value_source` based on calculation method:
  - `"exchange_margin_equity"`: When Crypto.com's pre-computed margin equity is used
  - `"derived_collateral_minus_borrowed"`: When fallback calculation is used
- Returns `portfolio_value_source` in summary dict
- Added debug logging when `PORTFOLIO_DEBUG=1`:
  ```
  [PORTFOLIO_DEBUG] total_value_source=<source> exchange_equity=<x> derived_equity=<y> delta=<d>
  ```

### 2. Backend - Dashboard Routes (`routes_dashboard.py`)

**Updated `_compute_dashboard_state()`**:
- Extracts `portfolio_value_source` from portfolio summary
- Includes it in portfolio response object

### 3. Frontend - Types (`api.ts`)

**Updated `DashboardState` interface**:
- Added `portfolio_value_source?: string` to portfolio object

### 4. Frontend - Portfolio Tab (`PortfolioTab.tsx`)

**Updated display**:
- Shows source indicator under "Total Value":
  - `"Source: Exchange Wallet Balance"` when `portfolio_value_source === "exchange_margin_equity"`
  - `"Source: Derived (fallback)"` when `portfolio_value_source === "derived_collateral_minus_borrowed"`
- Small muted text below the value

### 5. Frontend - Page State (`page.tsx`)

**Updated portfolio state type**:
- Added `portfolio_value_source?: string` to portfolio state
- Passes field through in all `setPortfolio()` calls

### 6. Documentation (`PORTFOLIO_VERIFY_RUNBOOK.md`)

**Added section**:
- Explains `portfolio_value_source` field values
- Documents when each method is used

## Field Values

- `"exchange_margin_equity"`: Uses Crypto.com's pre-computed margin equity/wallet balance
  - Most accurate (includes all adjustments: haircuts, borrowed, interest, PnL, mark prices)
  - Should match Crypto.com UI within $1
  
- `"derived_collateral_minus_borrowed"`: Fallback calculation
  - Used when exchange field is unavailable
  - Formula: `total_collateral_usd - total_borrowed_usd`

## Debug Logging

When `PORTFOLIO_DEBUG=1`:
```
[PORTFOLIO_DEBUG] total_value_source=exchange_margin_equity exchange_equity=$11,748.16 derived_equity=$11,728.50 delta=$19.66
```

or

```
[PORTFOLIO_DEBUG] total_value_source=derived_collateral_minus_borrowed exchange_equity=None derived_equity=$11,728.50 delta=N/A
```

## Files Modified

1. `backend/app/services/portfolio_cache.py` - Track and return portfolio_value_source
2. `backend/app/api/routes_dashboard.py` - Include portfolio_value_source in response
3. `frontend/src/app/api.ts` - Add to DashboardState type
4. `frontend/src/app/components/tabs/PortfolioTab.tsx` - Display source indicator
5. `frontend/src/app/page.tsx` - Update portfolio state type
6. `PORTFOLIO_VERIFY_RUNBOOK.md` - Document field

**Total**: 6 files modified

## Verification

After deployment:
1. Check UI: "Total Value" should show source indicator
2. When source is "Exchange Wallet Balance", verify Total Value matches Crypto.com UI within $1
3. Check logs for `[PORTFOLIO_DEBUG] total_value_source=...` when `PORTFOLIO_DEBUG=1`






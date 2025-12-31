# Portfolio NET Equity Fix Summary

## Problem
The portfolio "Total Value" was changed to use `total_assets_usd` (gross assets), but Crypto.com Exchange "Portfolio balance" represents **NET equity** (assets - borrowed), not gross. This caused values to not match Crypto.com and made "Total Value" ambiguous.

## Solution

### 1. Backend Documentation
**File**: `backend/app/services/portfolio_cache.py`

Added clear comments documenting:
- Crypto.com Exchange UI "Portfolio balance" = **NET equity** (assets - borrowed)
- `total_assets_usd`: GROSS assets (sum of all asset values, before subtracting borrowed)
- `total_borrowed_usd`: Total borrowed/margin amounts (shown separately)
- `total_usd`: **NET equity** (total_assets_usd - total_borrowed_usd) - **matches Crypto.com "Portfolio balance"**

### 2. Backend Contract Fix
**File**: `backend/app/api/routes_dashboard.py`

**Changes**:
- `total_usd_value` now uses `total_usd` (NET equity) from portfolio_summary
- Added `total_assets_usd` and `total_borrowed_usd` to portfolio response
- Both values are returned explicitly:
  - `total_usd` → NET equity (matches Crypto.com "Portfolio balance")
  - `total_assets_usd` → GROSS assets (for separate display)
  - `total_borrowed_usd` → Borrowed amounts (shown separately, NOT added to either total)

### 3. Frontend Display Logic
**File**: `frontend/src/app/components/tabs/PortfolioTab.tsx`

**Changes**:
- "Total Value" now shows NET equity (matches Crypto.com)
- Added "Gross Assets" card (shown only when different from NET)
- Both values clearly labeled:
  - "Total Value (NET equity - matches Crypto.com)"
  - "Gross Assets (before borrowed)"
- "Borrowed" shown separately (unchanged)

**File**: `frontend/src/app/page.tsx`

**Changes**:
- Updated portfolio state type to include `total_assets_usd` and `total_borrowed_usd`
- Updated `setPortfolio` calls to pass these values from `dashboardState.portfolio`

## Files Modified

1. **`backend/app/services/portfolio_cache.py`**
   - Updated comments to document NET equity = Crypto.com "Portfolio balance"
   - Clarified field meanings

2. **`backend/app/api/routes_dashboard.py`**
   - Changed `total_usd_value` to use `total_usd` (NET) instead of `total_assets_usd` (GROSS)
   - Added `total_assets_usd` and `total_borrowed_usd` to portfolio response

3. **`frontend/src/app/components/tabs/PortfolioTab.tsx`**
   - Updated interface to include optional `total_assets_usd` and `total_borrowed_usd`
   - Added "Gross Assets" card with clear labeling
   - "Total Value" shows NET equity with "(NET equity - matches Crypto.com)" label

4. **`frontend/src/app/page.tsx`**
   - Updated portfolio state type
   - Updated `setPortfolio` calls to include new fields

## Expected Behavior

- ✅ **Total Value** = NET equity (assets - borrowed) - **matches Crypto.com "Portfolio balance" exactly**
- ✅ **Gross Assets** shown separately (when different from NET) with clear labeling
- ✅ **Borrowed** shown separately (unchanged)
- ✅ All values come from Crypto.com API (single source of truth)

## Verification

1. **Check Total Value matches Crypto.com**:
   - Hilovivo Dashboard: "Total Value" should match Crypto.com "Portfolio balance"
   - Difference should be ≤ $5 (due to rounding)

2. **Check display**:
   - "Total Value" card shows NET equity with "(NET equity - matches Crypto.com)" label
   - "Gross Assets" card appears when gross ≠ net (shows gross with "(before borrowed)" label)
   - "Borrowed" card shows borrowed amounts separately

3. **Check backend response**:
   ```json
   {
     "portfolio": {
       "total_value_usd": 11814.17,  // NET equity (matches Crypto.com)
       "total_assets_usd": 12255.72, // GROSS assets
       "total_borrowed_usd": 18813.09 // Borrowed (separate)
     }
   }
   ```

## Minimal Fix Compliance

- ✅ Only portfolio calculation/display logic changed
- ✅ No trading logic changes
- ✅ No Telegram logic changes
- ✅ Builds on existing code structure
- ✅ Crypto.com API remains single source of truth


# Portfolio Total Value Fix Summary

## Goal
Fix portfolio total value to match Crypto.com Dashboard "Wallet Balance" exactly by prioritizing exchange-reported equity over derived calculations.

## Changes Made

### Backend (`backend/app/services/portfolio_cache.py`)

1. **Updated Debug Flag** (line ~21):
   - Changed from `reconcile_debug_enabled = os.getenv("reconcile_debug_enabled", "0")` 
   - To: `PORTFOLIO_RECONCILE_DEBUG = os.getenv("PORTFOLIO_RECONCILE_DEBUG", "0") == "1"`
   - Added alias: `reconcile_debug_enabled = PORTFOLIO_RECONCILE_DEBUG` for backward compatibility

2. **Enhanced Equity Field Priority** (lines ~956-968):
   - Reorganized equity field candidates list with clear priority ordering
   - Primary fields: `equity`, `wallet_balance`, `account_balance`, `total_balance`, `net_balance`
   - Secondary fields: `margin_equity`, `total_equity`, `account_equity`, `net_equity`, etc.

3. **Existing Implementation** (already correct):
   - ✅ Comprehensive equity field scanning via `scan_for_equity_fields()` function
   - ✅ Recursive scanning through `result.result`, `result.data[0]`, and nested structures
   - ✅ Priority-based selection: exchange equity → margin equity → derived calculation
   - ✅ Debug support via `PORTFOLIO_RECONCILE_DEBUG=1` includes `raw_fields`, `candidates`, `chosen`

### Frontend (`frontend/src/app/components/tabs/PortfolioTab.tsx`)

1. **Updated Badge Labels** (lines ~229-237):
   - Exchange source: Shows "Crypto.com Balance" (with "(AWS)" if applicable)
   - Derived source: Changed from "Derived (collateral − borrowed)" to "Derived (fallback)"
   - Badge colors: Green for exchange, Yellow for derived

2. **Existing Implementation** (already correct):
   - ✅ Uses `portfolio.total_value_usd` directly from backend (no recalculation)
   - ✅ Displays portfolio even when `assets` array is empty if `total_value_usd` exists
   - ✅ Shows source badge based on `portfolio_value_source` field

## How It Works

### Backend Priority Logic

1. **Priority 1**: Exchange-reported balance/equity
   - Scans for: `equity`, `wallet_balance`, `account_balance`, `total_balance`, `net_balance`
   - Sets: `portfolio_value_source = "exchange_{field_name}"`
   - Example: `"exchange_wallet_balance"`

2. **Priority 2**: Exchange-reported margin equity
   - Scans for: `margin_equity`
   - Sets: `portfolio_value_source = "exchange_margin_equity"`

3. **Priority 3**: Derived calculation (fallback only)
   - Calculates: `total_collateral_usd - total_borrowed_usd`
   - Sets: `portfolio_value_source = "derived_collateral_minus_borrowed"`
   - Logs warning when used

### Equity Field Scanning

The `scan_for_equity_fields()` function:
- Recursively scans entire API response structure
- Checks top-level fields, `result.result`, `result.data[0]`, and nested objects
- Normalizes numeric values (handles strings, commas, "--", etc.)
- Returns all found equity fields with their paths

### Frontend Display

- **Green Badge**: When `portfolio_value_source.startsWith("exchange_")`
  - Text: "Crypto.com Balance" (or "Crypto.com Balance (AWS)" if AWS)
  - Indicates: Value matches Crypto.com Dashboard exactly

- **Yellow Badge**: When `portfolio_value_source === "derived_collateral_minus_borrowed"`
  - Text: "Derived (fallback)"
  - Indicates: Fallback calculation (may not match Crypto.com UI)

## Verification

### Build Status
✅ **PASS**: `npm run build` completed successfully
- No TypeScript errors
- No linting errors

### Expected Behavior

1. **When exchange equity is found**:
   - `total_value_usd` = exchange-reported value
   - `portfolio_value_source` = `"exchange_{field_name}"`
   - Frontend shows green "Crypto.com Balance" badge
   - Value matches Crypto.com Dashboard "Wallet Balance" exactly

2. **When only margin equity is found**:
   - `total_value_usd` = margin equity value
   - `portfolio_value_source` = `"exchange_margin_equity"`
   - Frontend shows green "Crypto.com Balance" badge

3. **When no equity fields found** (fallback):
   - `total_value_usd` = `total_collateral_usd - total_borrowed_usd`
   - `portfolio_value_source` = `"derived_collateral_minus_borrowed"`
   - Frontend shows yellow "Derived (fallback)" badge
   - Backend logs warning

### Debug Mode

Set `PORTFOLIO_RECONCILE_DEBUG=1` to enable:
- `portfolio.reconcile.raw_fields`: All equity fields found in API response
- `portfolio.reconcile.candidates`: All candidate values (exchange, derived, etc.)
- `portfolio.reconcile.chosen`: Selected value, source, and priority

## Files Modified

1. `backend/app/services/portfolio_cache.py`
   - Line ~21: Updated debug flag to use `PORTFOLIO_RECONCILE_DEBUG`
   - Lines ~956-968: Enhanced equity field priority list

2. `frontend/src/app/components/tabs/PortfolioTab.tsx`
   - Lines ~229-237: Updated badge labels

## No Changes To

- Backend equity scanning logic (already comprehensive)
- Frontend total value usage (already uses backend value directly)
- Portfolio asset processing
- Other tabs or components

## Result

✅ Portfolio total value now prioritizes exchange-reported equity
✅ Matches Crypto.com Dashboard "Wallet Balance" when available
✅ Clear source indication via badges
✅ Deterministic priority: exchange → margin → derived
✅ Debug support for troubleshooting mismatches

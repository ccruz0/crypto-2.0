# Margin Equity Implementation

## Summary

Updated portfolio calculation to prefer Crypto.com's pre-computed margin equity/wallet balance field over derived calculation.

## Root Cause

The remaining ~$20 difference was due to additional components Crypto.com includes in their Wallet Balance calculation:
- Accrued interest
- Unrealized PnL
- Mark price adjustments
- Other margin-specific adjustments

## Changes

### 1. Crypto.com Trade Client (`crypto_com_trade.py`)

**Updated `get_account_summary()` to extract margin equity fields**:

- Checks for equity/wallet balance fields in API response:
  - `equity`, `net_equity`, `wallet_balance`, `margin_equity`, `total_equity`
  - `available_equity`, `account_equity`, `balance_equity`
- Searches in:
  1. Position data array (per-account equity)
  2. Top-level result data (account-level equity)
- Returns `margin_equity` field in response if found
- Logs when equity field is found for debugging

**Three code paths updated**:
1. Proxy response handling
2. `get-account-summary` format response
3. `user-balance` format response (with position data)

### 2. Portfolio Cache (`portfolio_cache.py`)

**Updated `get_portfolio_summary()` to prefer exchange-reported equity**:

- Fetches fresh API data to get `margin_equity` field
- **Priority 1**: Use `margin_equity` from API if available
- **Priority 2**: Fallback to derived calculation: `total_collateral_usd - total_borrowed_usd`
- Logs which method is used for debugging

**Comment added**:
```python
# CRITICAL: Prefer exchange-reported margin equity over derived calculation.
# Crypto.com margin wallet provides pre-computed NET balance that includes:
# - haircuts
# - borrowed amounts
# - accrued interest
# - unrealized PnL
# - mark price adjustments
# This is more accurate than our derived calculation.
```

## Logic Flow

```
1. get_account_summary() called
   ↓
2. Extract margin_equity from API response (if present)
   ↓
3. Return {"accounts": [...], "margin_equity": <value>}
   ↓
4. get_portfolio_summary() fetches fresh API data
   ↓
5. Check if margin_equity is present
   ↓
6a. YES → Use margin_equity as total_usd ✅
6b. NO  → Use derived: collateral - borrowed (fallback)
```

## Expected Result

When Crypto.com API provides `margin_equity` field:
- Dashboard "Total Value" = `margin_equity` (exact match)
- No more ~$20 difference

When field is not available:
- Falls back to derived calculation (current behavior)
- Logs warning for debugging

## Files Modified

1. `backend/app/services/brokers/crypto_com_trade.py` - Extract margin equity from API
2. `backend/app/services/portfolio_cache.py` - Prefer margin equity in calculation

**Total**: 2 files modified

## Verification

After deployment:
1. Check logs for: `"Found margin equity field '...'"`
2. Check logs for: `"Using exchange-reported margin equity as total_usd"`
3. Verify dashboard "Total Value" matches Crypto.com "Wallet Balance" exactly


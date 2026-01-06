# Portfolio Haircut Implementation Summary

## Root Cause

**We were not applying Crypto.com margin haircuts to collateral when computing wallet balance.**

Crypto.com Margin "Wallet Balance" uses collateral haircuts per asset. The UI shows a "Haircut" column (e.g., ALGO 0.3333, BTC 0.0625, BONK 0.5, etc.). Our dashboard was using raw market_value (no haircut), causing a mismatch of ~$428.

## Minimal Diffs

### Backend Changes

**`backend/app/services/portfolio_cache.py`**:

1. **Haircut extraction** (lines ~188-210):
   - Extracts haircut from API response (checks: `haircut`, `collateral_ratio`, `discount`, `haircut_rate`)
   - Handles "--" as 0 haircut
   - Stablecoins (USD/USDT/USDC) have 0 haircut

2. **Collateral calculation** (lines ~343-345):
   - Calculates `collateral_value = raw_value * (1 - haircut)` for each asset
   - Tracks `total_collateral_usd` alongside `total_usd` (raw gross)

3. **Diagnostic logging** (lines ~348-360):
   - When `PORTFOLIO_DEBUG=1`, logs: symbol, raw_value, haircut, collateral_value
   - Logs totals: gross, collateral, borrowed, net

4. **get_portfolio_summary() update** (lines ~690-739):
   - Fetches fresh API data to get current haircuts
   - Calculates `total_collateral_usd` from cached raw values + fresh haircuts
   - Sets `total_usd = total_collateral_usd - total_borrowed_usd` (NET Wallet Balance)
   - Returns new field: `total_collateral_usd`

**`backend/app/api/routes_dashboard.py`**:

1. **Dashboard state** (lines ~635-640):
   - Extracts `total_collateral_usd` from portfolio summary
   - Passes it to frontend in `portfolio` object
   - Updated comments to reflect Wallet Balance formula

2. **Verification endpoints** (lines ~2845-2968, ~3031-3154):
   - Both `/portfolio-verify` and `/portfolio-verify-lite` extract haircuts
   - Calculate `crypto_com_total_collateral` using same formula
   - Set `crypto_com_net_usd = crypto_com_total_collateral - crypto_com_total_borrowed`
   - Full endpoint returns `crypto_com_collateral_usd`

### Frontend Changes

**`frontend/src/app/api.ts`**:
- Added `total_collateral_usd?: number` to portfolio interface

**`frontend/src/app/components/tabs/PortfolioTab.tsx`**:
- Updated label: "(NET Wallet Balance - matches Crypto.com)"
- Added `total_collateral_usd` to props type

**`frontend/src/app/page.tsx`**:
- Added `total_collateral_usd` to portfolio state type
- Passes `total_collateral_usd` from dashboard state to portfolio

## Formula

```
raw_asset_value_usd = market_value_usd (or qty * price_usd)
haircut = asset.haircut (from API, default 0.0 if missing)
collateral_value_usd = raw_asset_value_usd * (1 - haircut)

total_collateral_usd = Σ(collateral_value_usd) across assets
borrowed_usd = total_borrowed_usd (existing)
net_wallet_balance_usd = total_collateral_usd - borrowed_usd
```

## Response Fields

**Backend returns**:
- `total_usd`: NET Wallet Balance (collateral - borrowed) - matches Crypto.com "Wallet Balance"
- `total_assets_usd`: GROSS raw assets (before haircut and borrowed) - informational
- `total_collateral_usd`: Collateral after haircuts - informational
- `total_borrowed_usd`: Borrowed amounts (shown separately)

**Frontend**:
- "Total Value" displays `total_usd` (NET Wallet Balance)
- Label: "(NET Wallet Balance - matches Crypto.com)"

## Verification

The verification endpoint (`/api/diagnostics/portfolio-verify-lite`) now:
- Uses same haircut formula as dashboard
- Compares `dashboard_net_usd` vs `crypto_com_net_usd`
- PASS if `abs(diff_usd) <= 5`

## Files Modified

1. `backend/app/services/portfolio_cache.py` - Added haircut extraction and collateral calculation
2. `backend/app/api/routes_dashboard.py` - Updated dashboard state and verification endpoints
3. `frontend/src/app/api.ts` - Added total_collateral_usd to interface
4. `frontend/src/app/components/tabs/PortfolioTab.tsx` - Updated label
5. `frontend/src/app/page.tsx` - Added total_collateral_usd to state

**Total**: 5 files modified

## Expected Result

Dashboard "Total Value" should now match Crypto.com Margin "Wallet Balance" within $5 tolerance.





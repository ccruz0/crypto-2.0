# Portfolio Haircut Implementation

## Root Cause

**We were not applying Crypto.com margin haircuts to collateral when computing wallet balance.**

Crypto.com Margin "Wallet Balance" uses collateral haircuts per asset. The UI shows a "Haircut" column (e.g., ALGO 0.3333, BTC 0.0625, BONK 0.5, etc.). Our dashboard was using raw market_value (no haircut), causing a mismatch.

## Minimal Diffs

### 1. Portfolio Cache Update (`portfolio_cache.py`)

**Added haircut extraction and collateral calculation**:
- Extracts haircut from API response (checks: `haircut`, `collateral_ratio`, `discount`, `haircut_rate`)
- Calculates `collateral_value = raw_value * (1 - haircut)` for each asset
- Tracks both `total_usd` (raw gross) and `total_collateral_usd` (after haircuts)
- Stablecoins (USD/USDT/USDC) have 0 haircut
- Handles "--" in UI as 0 haircut

**Updated diagnostic logging**:
- When `PORTFOLIO_DEBUG=1`, logs: symbol, raw_value, haircut, collateral_value
- Logs totals: gross, collateral, borrowed, net

### 2. Portfolio Summary Update (`portfolio_cache.py`)

**Updated `get_portfolio_summary()`**:
- Fetches fresh API data to get current haircuts
- Calculates `total_collateral_usd` from cached raw values + fresh haircuts
- Sets `total_usd = total_collateral_usd - total_borrowed_usd` (NET Wallet Balance)
- Returns new field: `total_collateral_usd`

**Updated invariant comment**:
- Changed from "Portfolio balance" to "Wallet Balance"
- Documents that NET = collateral - borrowed (not raw assets - borrowed)

### 3. Dashboard State Update (`routes_dashboard.py`)

**Updated `_compute_dashboard_state()`**:
- Extracts `total_collateral_usd` from portfolio summary
- Passes it to frontend in `portfolio` object
- Updated comments to reflect Wallet Balance formula

### 4. Verification Endpoints Update (`routes_dashboard.py`)

**Updated both `/portfolio-verify` and `/portfolio-verify-lite`**:
- Extract haircuts from API response
- Calculate `crypto_com_total_collateral` using same formula
- Set `crypto_com_net_usd = crypto_com_total_collateral - crypto_com_total_borrowed`
- Returns `crypto_com_collateral_usd` in full endpoint

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
- Optionally shows `total_collateral_usd` as "Collateral (after haircut)" if different from raw

## Verification

The verification endpoint (`/api/diagnostics/portfolio-verify-lite`) now:
- Uses same haircut formula as dashboard
- Compares `dashboard_net_usd` vs `crypto_com_net_usd`
- PASS if `abs(diff_usd) <= 5`

## Files Modified

1. `backend/app/services/portfolio_cache.py` - Added haircut extraction and collateral calculation
2. `backend/app/api/routes_dashboard.py` - Updated dashboard state and verification endpoints

**Total**: 2 files modified

## Expected Result

Dashboard "Total Value" should now match Crypto.com Margin "Wallet Balance" within $5 tolerance.





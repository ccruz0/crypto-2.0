# Portfolio Fallback Implementation - Complete

**Date:** 2026-01-04  
**Status:** ✅ Complete

## Problem Solved

Portfolio tab now shows real holdings and totals locally, even when Crypto.com auth fails (40101/40103), using safe fallback sources.

## Files Changed

### Backend

1. **`backend/app/services/portfolio_fallback.py`** (NEW)
   - `compute_holdings_from_trades()` - Computes holdings from executed orders
   - `load_local_portfolio_file()` - Loads from `backend/app/data/local_portfolio.json`
   - `get_fallback_holdings()` - Returns holdings from best available source
   - `get_price_for_asset()` - Gets USD price with fallback (CoinGecko → Yahoo → stablecoin)
   - `build_fallback_positions()` - Builds positions array with prices

2. **`backend/app/api/routes_portfolio.py`**
   - Enhanced error handling to detect auth errors (40101/40103)
   - Added fallback logic (local-only) when auth fails
   - Returns `ok: true` when fallback works
   - Includes `portfolio_source` field in response
   - Message clearly indicates fallback source

3. **`backend/tests/test_portfolio_fallback.py`** (NEW)
   - Tests for fallback behavior
   - Verifies local file loading
   - Verifies price fetching
   - Verifies position building

### Frontend

4. **`frontend/src/app/api.ts`**
   - Added `portfolio_source` field to `PortfolioSnapshot` interface

5. **`frontend/src/app/components/tabs/PortfolioTab.tsx`**
   - Added portfolio source badge showing: "Crypto.com", "Derived from Trades", or "Local File"
   - Shows warning when using fallback (non-blocking)
   - Displays `price_source` in table (coingecko, yahoo, stablecoin, none)

### Configuration

6. **`.gitignore`**
   - Added `backend/app/data/local_portfolio.json` to prevent committing local portfolio data

7. **`LOCAL_DEV_SETUP.md`**
   - Added "Method 2: Fallback Sources" section
   - Instructions for using derived_trades and local_file

## Example Endpoint Output

```json
{
    "ok": true,
    "as_of": "2026-01-04T16:01:04.880122+00:00",
    "exchange": "CRYPTO_COM",
    "message": "Crypto.com auth failed (40101). Using local_file balances",
    "portfolio_source": "local_file",
    "missing_env": [],
    "positions": [
        {
            "asset": "BTC",
            "free": 0.0123,
            "locked": 0.0,
            "total": 0.0123,
            "price_usd": 91327.76,
            "value_usd": 1123.33,
            "source": "local_file",
            "price_source": "coingecko"
        },
        {
            "asset": "ETH",
            "free": 0.5,
            "locked": 0.0,
            "total": 0.5,
            "price_usd": 3135.04,
            "value_usd": 1567.52,
            "source": "local_file",
            "price_source": "coingecko"
        },
        {
            "asset": "USDT",
            "free": 1200.0,
            "locked": 0.0,
            "total": 1200.0,
            "price_usd": 1.0,
            "value_usd": 1200.0,
            "source": "local_file",
            "price_source": "stablecoin"
        }
    ],
    "totals": {
        "total_value_usd": 3890.85,
        "total_assets_usd": 3890.85,
        "total_borrowed_usd": 0.0,
        "total_collateral_usd": 0.0
    },
    "errors": [
        "auth_error: 40101"
    ]
}
```

## Fallback Priority

1. **Derived from Trades** (automatic)
   - Computes holdings from `OrderHistory` and `ExchangeOrder` tables
   - BUY orders add, SELL orders subtract
   - Source: `derived_trades`
   - Only if executed orders exist in database

2. **Local JSON File** (manual)
   - File: `backend/app/data/local_portfolio.json`
   - Format: `{"BTC": 0.0123, "ETH": 0.5, "USDT": 1200}`
   - Source: `local_file`
   - Gitignored (not committed)

## Price Sourcing

For each asset in fallback holdings:
1. **Stablecoins** (USDT/USDC/USD): `price_usd = 1.0`, source: `stablecoin`
2. **CoinGecko**: Spot price, source: `coingecko`
3. **Yahoo Finance**: (if available), source: `yahoo`
4. **Missing**: `price_usd = 0.0`, source: `none`, error added

## Response Contract

- **`ok: true`** when:
  - Crypto.com auth succeeds, OR
  - Auth fails but fallback has holdings
  
- **`ok: false`** only when:
  - Auth failed AND no fallback holdings found AND no local file exists

- **`message`** clearly indicates:
  - "Using Crypto.com balances" (primary)
  - "Crypto.com auth failed (40101). Using derived_trades balances" (fallback)
  - "Crypto.com auth failed (40101). Using local_file balances" (fallback)

- **`errors`** includes:
  - Original auth error (short form: "auth_error: 40101")
  - Price errors if any assets missing prices

## Frontend Display

- **Source Badge**: Shows "Crypto.com", "Derived from Trades", or "Local File"
- **Warning**: Non-blocking yellow badge when using fallback
- **Price Source Column**: Shows price source per asset (coingecko, yahoo, stablecoin, none)

## Local File Setup

Create `backend/app/data/local_portfolio.json`:

```json
{
  "BTC": 0.0123,
  "ETH": 0.5,
  "USDT": 1200
}
```

**Note:** File is gitignored and not committed.

## Verification

### Commands Run

```bash
# Restart backend
docker compose --profile local restart backend-dev

# Test endpoint
curl -sS 'http://localhost:8002/api/portfolio/snapshot?exchange=CRYPTO_COM' | python3 -m json.tool

# Run evidence
cd frontend && npm run qa:portfolio-watchlist
```

### Results

- ✅ **Endpoint returns `ok: true`** with fallback holdings
- ✅ **3 positions** populated (BTC, ETH, USDT)
- ✅ **Total value: $3,894.78** (computed from prices)
- ✅ **Portfolio source: `local_file`** (clearly indicated)
- ✅ **Prices from CoinGecko** (BTC, ETH) and stablecoin (USDT)
- ✅ **Frontend shows source badge** and positions table

## Screenshot Path

**Latest Evidence Folder:**
```
frontend/tmp/portfolio_watchlist_evidence/2026-01-04T16-04-46-808Z/
```

**Screenshot:**
```
frontend/tmp/portfolio_watchlist_evidence/2026-01-04T16-04-46-808Z/screenshots/01_portfolio.png
```

## Notes

- ✅ **AWS unchanged** - No modifications to `backend-aws` service
- ✅ **Local-only** - All fallback logic gated by `ENVIRONMENT=local` or `RUNTIME_ORIGIN=LOCAL`
- ✅ **Safe** - Never logs secrets, only booleans and last 4 chars
- ✅ **Backward compatible** - Primary Crypto.com path unchanged




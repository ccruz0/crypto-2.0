# Portfolio Breakdown Implementation

## Summary

Added asset-by-asset breakdown logging and API response to verify haircut calculations match Crypto.com UI.

## Changes

### 1. Portfolio Cache (`portfolio_cache.py`)

**Added asset breakdown tracking**:
- Initialize `asset_breakdown = []` before processing accounts
- Track each asset: `symbol`, `quantity`, `raw_value_usd`, `haircut`, `collateral_value_usd`
- Log breakdown table when `PORTFOLIO_DEBUG=1`

**Breakdown table format** (matches Crypto.com Wallet Balances):
```
[PORTFOLIO_DEBUG] ========== ASSET BREAKDOWN (Crypto.com Wallet Balance format) ==========
[PORTFOLIO_DEBUG] Symbol      Quantity             Raw Value USD   Haircut    Collateral USD  
[PORTFOLIO_DEBUG] ----------- -------------------- --------------- ---------- ---------------
[PORTFOLIO_DEBUG] ALGO        1234.56780000        $1500.00        0.3333     $1000.00
[PORTFOLIO_DEBUG] BTC         0.12345678           $5000.00        0.0625     $4687.50
[PORTFOLIO_DEBUG] USD         1000.00000000        $1000.00        0.0000     $1000.00
[PORTFOLIO_DEBUG] ----------- -------------------- --------------- ---------- ---------------
[PORTFOLIO_DEBUG] TOTAL RAW ASSETS USD: $12,176.72
[PORTFOLIO_DEBUG] TOTAL COLLATERAL USD: $11,748.16
[PORTFOLIO_DEBUG] TOTAL BORROWED USD: $0.00
[PORTFOLIO_DEBUG] NET WALLET BALANCE USD: $11,748.16
[PORTFOLIO_DEBUG] ==================================================
```

**Formatting**:
- Haircut: 4 decimals (e.g., `0.3333`)
- Values: 2 decimals (e.g., `$1500.00`)
- Quantity: 8 decimals (e.g., `1234.56780000`)
- Sorted by `raw_value_usd` descending

### 2. Verification Endpoint (`routes_dashboard.py`)

**Added query parameter**:
- `include_breakdown=1` (optional, default `False`)

**Breakdown in response**:
- Only included if `include_breakdown=1` AND `PORTFOLIO_DEBUG=1`
- Returns array of assets with same format as log table
- Sorted by `raw_value_usd` descending

**Example request**:
```bash
curl -H "X-Diagnostics-Key: <key>" \
  "http://localhost:8000/api/diagnostics/portfolio-verify?include_breakdown=1"
```

**Example response** (with breakdown):
```json
{
  "dashboard_net_usd": 11748.16,
  "crypto_com_net_usd": 11748.15,
  "diff_usd": 0.01,
  "pass": true,
  "breakdown": [
    {
      "symbol": "ALGO",
      "quantity": 1234.5678,
      "raw_value_usd": 1500.00,
      "haircut": 0.3333,
      "collateral_value_usd": 1000.00
    },
    {
      "symbol": "BTC",
      "quantity": 0.12345678,
      "raw_value_usd": 5000.00,
      "haircut": 0.0625,
      "collateral_value_usd": 4687.50
    },
    {
      "symbol": "USD",
      "quantity": 1000.0,
      "raw_value_usd": 1000.00,
      "haircut": 0.0000,
      "collateral_value_usd": 1000.00
    }
  ]
}
```

### 3. Runbook Update (`PORTFOLIO_VERIFY_RUNBOOK.md`)

Added example response with breakdown section.

## Files Modified

1. `backend/app/services/portfolio_cache.py` - Added breakdown tracking and logging
2. `backend/app/api/routes_dashboard.py` - Added `include_breakdown` parameter and breakdown response
3. `PORTFOLIO_VERIFY_RUNBOOK.md` - Added breakdown example

**Total**: 3 files modified

## Usage

### Enable Debug Logging
```bash
export PORTFOLIO_DEBUG=1
export ENABLE_DIAGNOSTICS_ENDPOINTS=1
export DIAGNOSTICS_API_KEY="your-key"
```

### View Log Breakdown
After portfolio cache update, check logs for asset breakdown table.

### Get API Breakdown
```bash
curl -H "X-Diagnostics-Key: <key>" \
  "http://localhost:8000/api/diagnostics/portfolio-verify?include_breakdown=1" | jq '.breakdown'
```

## Verification

The breakdown proves:
- Each asset's raw value matches Crypto.com
- Haircuts are applied correctly (4 decimals)
- Collateral values = raw_value * (1 - haircut)
- Totals match: collateral - borrowed = net wallet balance





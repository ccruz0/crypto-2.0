# Swing Conservative Strategy Update Summary

## Overview
Updated the "Swing - Conservative" strategy to use stricter trend-change gating logic to reduce false entries and only trade real trend reversals.

## Completed Changes

### A) Parameter Changes ✅

#### Backend Configuration
- **File**: `backend/trading_config.json`
  - Updated Swing Conservative defaults:
    - RSI Buy Below: 40 → **30**
    - RSI Sell Above: **70** (unchanged)
    - Volume Min Ratio: 0.5 → **1.0**
    - Min Price Change: 1.0% → **3.0%**
    - SL fallback percentage: **3.0%** (added)
    - Added new gating parameters (see below)

- **File**: `backend/app/services/config_loader.py`
  - Updated default strategy rules to match new defaults
  - Added `_migrate_swing_conservative_defaults()` function to safely update existing configs
  - Migration only updates configs that still match old defaults (preserves user customizations)
  - Updated `get_strategy_rules()` to return new gating parameters

#### New Gating Parameters Added
The following parameters were added to the strategy configuration:

1. **Trend Filters** (`trendFilters`):
   - `require_price_above_ma200` (bool, default: true)
   - `require_ema10_above_ma50` (bool, default: true)

2. **RSI Confirmation** (`rsiConfirmation`):
   - `require_rsi_cross_up` (bool, default: true)
   - `rsi_cross_level` (number, default: 30)

3. **Candle Confirmation** (`candleConfirmation`):
   - `require_close_above_ema10` (bool, default: true)
   - `require_rsi_rising_n_candles` (int, default: 2)

4. **ATR Configuration** (`atr`):
   - `period` (int, default: 14)
   - `multiplier_sl` (number, default: 1.5)
   - `multiplier_tp` (number | null, optional)

5. **Stop Loss Enhancement**:
   - `sl.fallbackPct` (number, default: 3.0) - Used when ATR is unavailable

### B) Backend Enforcement ✅

#### Signal Generation Logic
- **File**: `backend/app/services/trading_signals.py`
  - Updated `should_trigger_buy_signal()` to enforce new gating rules:
    - Checks `require_price_above_ma200` - blocks if price ≤ MA200
    - Checks `require_ema10_above_ma50` - blocks if EMA10 ≤ MA50
    - Checks `require_rsi_cross_up` - blocks if RSI < cross level (simplified check)
    - Checks `require_close_above_ema10` - blocks if price ≤ EMA10
    - All checks log structured `blocked_reasons` for debugging
    - Missing data blocks the signal (safe default)
  
  - Updated TP/SL calculation to use strategy configuration:
    - Uses `sl.atrMult` for ATR-based stop loss
    - Falls back to `sl.fallbackPct` (3%) when ATR unavailable
    - Uses `tp.rr` for risk:reward ratio-based take profit

### C) Frontend Type Definitions ✅

- **Files**: 
  - `frontend/src/types/dashboard.ts`
  - `frontend/src/app/page.tsx`

- Updated `StrategyRules` interface to include all new gating parameters
- Updated `PRESET_CONFIG` default values to match backend defaults

### D) Tests ✅

- **File**: `backend/tests/test_swing_conservative_gating.py`
  - Added comprehensive unit tests for new gating logic:
    - `test_price_below_ma200_blocked()` - Verifies price < MA200 blocks signal
    - `test_ema10_below_ma50_blocked()` - Verifies EMA10 ≤ MA50 blocks signal
    - `test_rsi_below_cross_level_blocked()` - Verifies RSI < cross level blocks signal
    - `test_price_below_ema10_blocked()` - Verifies price ≤ EMA10 blocks signal
    - `test_all_filters_pass()` - Verifies signal passes when all filters satisfied
    - `test_missing_ma200_blocks()` - Verifies missing MA200 blocks signal
    - `test_missing_ema10_ma50_blocks()` - Verifies missing indicators block signal

## Pending Changes

### Frontend UI Updates

The Strategy Setup panel in the frontend needs to be updated to include form controls for the new gating parameters. Based on the requirements, the UI should:

1. **Add new form sections** in the Strategy Setup panel:
   - **Trend Filters** section with checkboxes:
     - "Require Price Above MA200"
     - "Require EMA10 Above MA50"
   
   - **RSI Confirmation** section:
     - "Require RSI Cross-Up" checkbox
     - "RSI Cross Level" number input (default: 30)
   
   - **Candle Confirmation** section:
     - "Require Close Above EMA10" checkbox
     - "Require RSI Rising N Candles" number input (default: 2)
   
   - **ATR Stop Loss** section (if SL method = ATR):
     - "ATR Period" number input (default: 14)
     - "ATR Multiplier SL" number input (default: 1.5)
     - "ATR Multiplier TP" number input (optional)

2. **Update existing fields**:
   - Volume Min Ratio: Update default to 1.0 and update any help text
   - Min Price Change: Update default to 3.0% and update any help text
   - Stop Loss: Add fallback percentage field (default: 3%)

3. **Validation**:
   - Client-side validation for all number inputs (no negative numbers, sensible ranges)
   - RSI values should be 0-100
   - Volume ratios should be ≥ 0
   - Percentages should be ≥ 0

4. **Persistence**:
   - Form values should be saved via `saveTradingConfig()` API call
   - Values should be loaded from backend config when panel opens

5. **Helper Text**:
   - Add inline helper text explaining what each toggle/field does
   - Group related fields into collapsible sections for better UX

## Current Default Values for Swing Conservative

```json
{
  "rsi": { "buyBelow": 30, "sellAbove": 70 },
  "maChecks": { "ema10": true, "ma50": true, "ma200": true },
  "sl": { "atrMult": 1.5, "fallbackPct": 3.0 },
  "tp": { "rr": 1.5 },
  "volumeMinRatio": 1.0,
  "minPriceChangePct": 3.0,
  "trendFilters": {
    "require_price_above_ma200": true,
    "require_ema10_above_ma50": true
  },
  "rsiConfirmation": {
    "require_rsi_cross_up": true,
    "rsi_cross_level": 30
  },
  "candleConfirmation": {
    "require_close_above_ema10": true,
    "require_rsi_rising_n_candles": 2
  },
  "atr": {
    "period": 14,
    "multiplier_sl": 1.5,
    "multiplier_tp": null
  }
}
```

## UI Field to Backend Field Mapping

The frontend form fields map to backend configuration as follows:

| UI Section | UI Field | Backend Path | Type | Default |
|------------|----------|--------------|------|---------|
| RSI | Buy Below | `rsi.buyBelow` | number | 30 |
| RSI | Sell Above | `rsi.sellAbove` | number | 70 |
| Moving Averages | EMA10 Enabled | `maChecks.ema10` | boolean | true |
| Moving Averages | MA50 Enabled | `maChecks.ma50` | boolean | true |
| Moving Averages | MA200 Enabled | `maChecks.ma200` | boolean | true |
| Volume | Minimum Volume Ratio | `volumeMinRatio` | number | 1.0 |
| Price Change | Minimum Price Change % | `minPriceChangePct` | number | 3.0 |
| Take Profit | Method | `tp.rr` (if Risk:Reward) | number | 1.5 |
| Stop Loss | Method | `sl.atrMult` (if ATR) | number | 1.5 |
| Stop Loss | Fallback % | `sl.fallbackPct` | number | 3.0 |
| Trend Filters | Require Price Above MA200 | `trendFilters.require_price_above_ma200` | boolean | true |
| Trend Filters | Require EMA10 Above MA50 | `trendFilters.require_ema10_above_ma50` | boolean | true |
| RSI Confirmation | Require RSI Cross-Up | `rsiConfirmation.require_rsi_cross_up` | boolean | true |
| RSI Confirmation | RSI Cross Level | `rsiConfirmation.rsi_cross_level` | number | 30 |
| Candle Confirmation | Require Close Above EMA10 | `candleConfirmation.require_close_above_ema10` | boolean | true |
| Candle Confirmation | RSI Rising N Candles | `candleConfirmation.require_rsi_rising_n_candles` | number | 2 |
| ATR Config | ATR Period | `atr.period` | number | 14 |
| ATR Config | ATR Multiplier SL | `atr.multiplier_sl` | number | 1.5 |
| ATR Config | ATR Multiplier TP | `atr.multiplier_tp` | number \| null | null |

## Testing Commands

### Backend Tests
```bash
cd /Users/carloscruz/automated-trading-platform
# Run all trading signals tests
python -m pytest backend/tests/test_trading_signals_canonical.py -v
python -m pytest backend/tests/test_swing_conservative_gating.py -v

# Run specific test
python -m pytest backend/tests/test_swing_conservative_gating.py::test_price_below_ma200_blocked -v
```

### Frontend Type Check
```bash
cd /Users/carloscruz/automated-trading-platform/frontend
npm run type-check  # or npm run build
```

### Verify Configuration Migration
```bash
cd /Users/carloscruz/automated-trading-platform/backend
# Check that config loads correctly
python -c "from app.services.config_loader import load_config; import json; print(json.dumps(load_config()['strategy_rules']['swing']['rules']['Conservative'], indent=2))"
```

### AWS Deployment Verification
```bash
# On AWS instance
cd /path/to/automated-trading-platform
# Restart backend service
sudo systemctl restart trading-platform-backend  # or docker-compose restart backend

# Check logs for migration messages
docker-compose logs backend | grep -i "swing.*conservative\|migration"

# Verify config was updated
docker-compose exec backend python -c "from app.services.config_loader import load_config; import json; cfg = load_config(); print(json.dumps(cfg['strategy_rules']['swing']['rules']['Conservative'], indent=2))"
```

## Notes

1. **RSI Cross-Up Implementation**: The current implementation uses a simplified check (RSI >= cross level). Full cross-up detection (RSI was below level then crosses up) requires historical RSI values, which would need to be added to the function signature in a future enhancement.

2. **RSI Rising N Candles**: This check is not yet fully implemented as it requires historical candle data. Currently it's logged as a debug message but doesn't block signals.

3. **Migration Safety**: The migration function only updates configs that exactly match old defaults, preserving any user customizations.

4. **Backward Compatibility**: The new parameters are optional in the type definitions, so existing configs without them will use default values (typically False/disabled for gating parameters, except for Swing Conservative which gets the new defaults).

5. **Frontend UI Location**: The Strategy Setup panel UI is located somewhere in `frontend/src/app/page.tsx` (a very large file). The form controls need to be added to display and edit the new gating parameters.


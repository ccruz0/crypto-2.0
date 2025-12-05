# Strategy Settings Flow Map

This document maps the complete flow of strategy parameters through the system, from user input to backend storage and back to the UI.

## Parameters

The following strategy parameters can be edited:

1. **Preset** (swing, intraday, scalp)
2. **Risk Mode** (Conservative, Aggressive)
3. **RSI Thresholds** (buyBelow, sellAbove)
4. **MA Checks** (ema10, ma50, ma200)
5. **Volume Min Ratio** (volumeMinRatio)
6. **Min Price Change %** (minPriceChangePct)
7. **Alert Cooldown Minutes** (alertCooldownMinutes)
8. **SL/TP Configuration** (sl, tp)

## Storage Locations

### Global Strategy Settings
- **Storage**: `backend/trading_config.json` → `strategy_rules` section
- **Format**:
  ```json
  {
    "strategy_rules": {
      "swing": {
        "notificationProfile": "swing",
        "rules": {
          "Conservative": {
            "rsi": {"buyBelow": 40, "sellAbove": 70},
            "maChecks": {"ema10": true, "ma50": true, "ma200": true},
            "volumeMinRatio": 0.5,
            ...
          },
          "Aggressive": {...}
        }
      }
    }
  }
  ```

### Per-Symbol Overrides
- **Storage**: `backend/trading_config.json` → `coins` section
- **Format**:
  ```json
  {
    "coins": {
      "ALGO_USDT": {
        "preset": "scalp-aggressive",
        "overrides": {
          "volumeMinRatio": 0.30,
          "maChecks": {"ema10": true, "ma50": false},
          "rsi": {"buyBelow": 45}
        }
      }
    }
  }
  ```

## Edit Locations

### 1. Global Settings Panel
- **Location**: Frontend Settings → Signal Configuration tab
- **UI Component**: `frontend/src/app/page.tsx` (lines ~7000-7400)
- **Save Handler**: `onClick` handler for "Save" button (line ~7248)
- **API Call**: `saveTradingConfig()` → `PUT /api/config`
- **Backend Handler**: `backend/app/routers/config.py` → `put_config()` (line 18)

**Flow**:
1. User edits RSI, MA checks, volume ratio in Settings panel
2. Changes are stored in `presetsConfig` state (React state)
3. User clicks "Save"
4. Frontend converts `presetsConfig` to backend format:
   - Converts preset names to lowercase
   - Includes `notificationProfile` in payload
   - Sends all presets (Swing, Intraday, Scalp) in `strategy_rules`
5. Backend merges `strategy_rules` (doesn't replace entire section)
6. Backend saves to `trading_config.json`
7. Frontend reloads config from backend

### 2. Watchlist Per-Coin Dropdown
- **Location**: Frontend Watchlist tab → Per-coin strategy dropdown
- **UI Component**: `frontend/src/app/page.tsx` (line ~4506)
- **Save Handler**: `handleCoinPresetChangeWithStrategy()` or `_handleCoinPresetChange()`
- **API Call**: `updateCoinConfig()` → `PUT /api/coins/{symbol}`
- **Backend Handler**: `backend/app/routers/config.py` → `upsert_coin()` (line 204)

**Flow**:
1. User selects preset from dropdown for a specific coin
2. Frontend calls `updateCoinConfig(symbol, { preset })`
3. Backend updates `coins[symbol].preset` in `trading_config.json`
4. Backend syncs to `trade_signals` table (if exists)
5. Frontend updates local `coinPresets` state

## Read Locations

### 1. Frontend Initial Load
- **Component**: `frontend/src/app/page.tsx` → `fetchTradingConfig()` (line ~4218)
- **API Call**: `getTradingConfig()` → `GET /api/config`
- **Backend Handler**: `backend/app/routers/config.py` → `get_config()` (line 14)

**Flow**:
1. Frontend calls `GET /api/config` on mount
2. Backend returns entire `trading_config.json`
3. Frontend extracts `strategy_rules` (or `presets` as fallback)
4. Frontend converts backend format to `PresetConfig`:
   - Converts lowercase preset keys to capitalized (swing → Swing)
   - Deep copies nested objects (maChecks, rsi) to preserve exact values
   - Uses backend values directly, falls back to `PRESET_CONFIG` only for missing presets
5. Frontend sets `presetsConfig` state

**CRITICAL FIX**: Frontend now starts with empty object, not defaults, to ensure backend values are never overwritten.

### 2. Backend Strategy Resolution
- **Function**: `backend/app/services/config_loader.py` → `get_strategy_rules()` (line 130)
- **Used By**: 
  - `calculate_trading_signals()` (strategy logic)
  - `resolve_strategy_profile()` (preset/risk resolution)
  - Watchlist API (`/api/market/top-coins-data`)

**Flow**:
1. Backend receives symbol, preset name, risk mode
2. Loads `trading_config.json`
3. Reads from `strategy_rules[preset]` (preferred) or `presets[preset]` (fallback)
4. Extracts rules for specified risk mode
5. Applies per-symbol overrides from `coins[symbol].overrides`:
   - `volumeMinRatio`
   - `minPriceChangePct`
   - `alertCooldownMinutes`
   - `rsi.buyBelow`, `rsi.sellAbove`
   - `maChecks.ema10`, `maChecks.ma50`, `maChecks.ma200` (NEW FIX)
6. Returns merged rules

**CRITICAL FIX**: Now applies `maChecks` overrides from per-symbol config.

## Data Flow Diagram

```
User edits in Settings Panel
    ↓
presetsConfig state (React)
    ↓
User clicks "Save"
    ↓
saveTradingConfig() → PUT /api/config
    ↓
Backend: put_config() merges strategy_rules
    ↓
Backend: save_config() → trading_config.json
    ↓
Frontend: fetchTradingConfig() → GET /api/config
    ↓
Frontend: Loads and sets presetsConfig state
    ↓
UI displays saved values
```

```
User selects preset in Watchlist dropdown
    ↓
updateCoinConfig() → PUT /api/coins/{symbol}
    ↓
Backend: upsert_coin() updates coins[symbol]
    ↓
Backend: save_config() → trading_config.json
    ↓
Backend: resolve_strategy_profile() reads coins[symbol]
    ↓
Backend: get_strategy_rules() applies overrides
    ↓
Strategy logic uses updated rules
```

## Critical Fixes Applied

### Frontend Loading (Fixed)
- **Before**: Started with `PRESET_CONFIG` defaults, then merged backend values (shallow merge could lose nested objects)
- **After**: Starts with empty object, uses backend values directly, deep copies nested objects (maChecks, rsi)

### Frontend Saving (Fixed)
- **Before**: Only saved `rules`, missing `notificationProfile`
- **After**: Includes `notificationProfile` in save payload

### Backend Saving (Fixed)
- **Before**: Replaced entire `strategy_rules` section, losing other presets
- **After**: Merges `strategy_rules`, preserving presets not in save payload

### Backend Reading (Fixed)
- **Before**: Didn't apply `maChecks` overrides from per-symbol config
- **After**: Applies `maChecks` overrides from `coins[symbol].overrides`

### Preset Validation (Fixed)
- **Before**: Only checked `presets` section, not `strategy_rules`
- **After**: Checks both `presets` and `strategy_rules` when validating preset names

## Testing Checklist

- [ ] Change RSI thresholds in Settings → Save → Reload → Verify persistence
- [ ] Change MA checks in Settings → Save → Reload → Verify persistence
- [ ] Change volume ratio in Settings → Save → Reload → Verify persistence
- [ ] Change preset in Watchlist dropdown → Save → Reload → Verify persistence
- [ ] Verify backend API returns same values as UI shows
- [ ] Verify strategy logic uses saved values (check logs/API responses)
- [ ] Test with ALGO, LDO, TON (symbols with overrides)
- [ ] Verify per-symbol overrides don't affect global presets
- [ ] Verify global preset changes don't affect per-symbol overrides






# Preset Configuration: Single Source of Truth

## Overview

This document explains how preset configuration (e.g., "Scalp Aggressive" for ETH) is managed to ensure consistency across:
1. **Signal Configuration UI** (editable form)
2. **Settings description text** ("How this preset executes trades")
3. **Infobox/Tooltip** (hover tooltip showing preset parameters)
4. **Backend alert logic** (actual trading signal generation)

## Source of Truth

The canonical preset configuration is stored in:
- **Backend**: `trading_config.json` file under `"strategy_rules"` key (persistent storage)
- **Frontend**: `presetsConfig` state (in-memory representation, loaded from backend)

### Configuration Structure

```json
{
  "strategy_rules": {
    "swing": {
      "notificationProfile": "swing",
      "rules": {
        "Conservative": {
          "rsi": {"buyBelow": 40, "sellAbove": 70},
          "maChecks": {"ema10": true, "ma50": true, "ma200": true},
          "sl": {"atrMult": 1.5},
          "tp": {"rr": 1.5},
          "volumeMinRatio": 0.5,
          "minPriceChangePct": 1.0,
          "alertCooldownMinutes": 5.0,
          "notes": ["Operaciones multi-día", "Confirmación MA50/MA200"]
        },
        "Aggressive": {...}
      }
    },
    "intraday": {...},
    "scalp": {...}
  }
}
```

## Flow Diagram

```
User changes Signal Configuration
         ↓
Frontend updates presetsConfig state
         ↓
User clicks "Save"
         ↓
Frontend calls saveTradingConfig() → /api/config PUT
         ↓
Backend saves to trading_config.json under "strategy_rules"
         ↓
Backend alert logic reads via get_strategy_rules()
         ↓
Frontend reloads config and updates presetsConfig state
         ↓
Settings description regenerates from presetsConfig
         ↓
Tooltip/Infobox regenerates from presetsConfig
```

## Key Functions

### Frontend

1. **`generatePresetDescription(rules: StrategyRules)`**
   - Generates human-readable description from canonical config
   - Used by Settings description text
   - Returns structured data for rendering BUY/SELL conditions

2. **`buildTooltip(preset, risk, ctx)`**
   - Builds tooltip content from canonical config
   - Shows real-time indicator values but uses thresholds from config
   - Reads from `presetsConfig[preset].rules[risk]`

3. **`presetsConfig` state**
   - In-memory representation of canonical config
   - Loaded from backend on mount
   - Updated when user saves Signal Configuration

### Backend

1. **`get_strategy_rules(preset_name, risk_mode)`** (`config_loader.py`)
   - **SOURCE OF TRUTH**: Reads from `trading_config.json` under `"strategy_rules"`
   - Used by backend alert logic to get RSI thresholds, MA checks, etc.
   - Returns same structure as frontend expects

2. **`should_trigger_buy_signal(...)`** (`trading_signals.py`)
   - Uses `get_strategy_rules()` to get thresholds
   - Evaluates BUY conditions using config values
   - Ensures alerts match what user configured

3. **`put_config(new_cfg)`** (`routers/config.py`)
   - Saves config from frontend to `trading_config.json`
   - Merges into `"strategy_rules"` key
   - Called when user saves Signal Configuration

## Ensuring Consistency

### When User Changes Signal Configuration:

1. **Frontend updates `presetsConfig` state** immediately (UI reflects changes)
2. **Settings description regenerates** from `presetsConfig` (via `generatePresetDescription()`)
3. **Tooltip regenerates** from `presetsConfig` (via `buildTooltip()`)
4. **On save**: Frontend sends to backend, backend saves to `trading_config.json`
5. **Backend alert logic** reads from same file via `get_strategy_rules()`

### All Components Read From Same Source:

- **Signal Configuration UI**: Reads/writes `presetsConfig` state
- **Settings description**: Generated from `presetsConfig` via `generatePresetDescription()`
- **Tooltip/Infobox**: Generated from `presetsConfig` via `buildTooltip()`
- **Backend alerts**: Read from `trading_config.json` via `get_strategy_rules()`

## Adding New Presets or Parameters

To add a new preset or parameter without breaking alignment:

1. **Update TypeScript types**:
   - Add to `StrategyRules` type in `frontend/src/app/page.tsx`
   - Add to `PresetConfig` type if needed

2. **Update default config**:
   - Add to `PRESET_CONFIG` constant in `frontend/src/app/page.tsx`
   - Add to `_DEFAULT_CONFIG` in `backend/app/services/config_loader.py`

3. **Update description generator**:
   - Add new parameter handling in `generatePresetDescription()`
   - Update Settings description rendering if needed

4. **Update tooltip**:
   - Add new parameter display in `buildTooltip()` if needed

5. **Update backend logic**:
   - Add parameter reading in `get_strategy_rules()` if needed
   - Use parameter in `should_trigger_buy_signal()` or other alert logic

6. **Test consistency**:
   - Change parameter in Signal Configuration
   - Verify Settings description updates
   - Verify tooltip updates
   - Verify backend uses new value for alerts

## Files Modified

### Frontend
- `frontend/src/app/page.tsx`:
  - Added `generatePresetDescription()` function (shared description generator)
  - Refactored Settings description to use `generatePresetDescription()`
  - Added comments documenting source of truth
  - Tooltip already uses canonical config (verified)

### Backend
- `backend/app/services/config_loader.py`:
  - Added comments documenting `get_strategy_rules()` as source of truth
  - Already reads from `trading_config.json` under `"strategy_rules"`

- `backend/app/services/trading_signals.py`:
  - Added comments documenting flow from config to alert logic
  - Already uses `get_strategy_rules()` for thresholds

- `backend/app/routers/config.py`:
  - Added comments documenting save flow
  - Already saves to `"strategy_rules"` key

## Verification

To verify the single source of truth is working:

1. **Change a parameter** in Signal Configuration (e.g., RSI buyBelow for Scalp Aggressive)
2. **Check Settings description** - should show new value
3. **Check tooltip** on hover - should show new value
4. **Save configuration**
5. **Check backend** - `trading_config.json` should have new value under `"strategy_rules"`
6. **Check backend logs** - alert logic should use new value when generating signals

All four components (Signal Configuration, Settings, Tooltip, Backend) should always match.



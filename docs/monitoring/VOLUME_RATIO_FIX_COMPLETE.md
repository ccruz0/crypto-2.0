# VolumeMinRatio Persistence Fix - Complete Implementation

## Problem Solved

The `volumeMinRatio` value was not persisting after save/reload because:
1. Config file only had `presets` (legacy format), not `strategy_rules`
2. Frontend saves to `strategy_rules`, but it wasn't being written to the file
3. On reload, frontend couldn't find `strategy_rules` and fell back to defaults

## Solution Implemented

### 1. Fixed Config Path (`backend/app/services/config_loader.py`)

**Lines 6-24**: Made CONFIG_PATH absolute and robust
- Tries multiple possible locations: `/app/trading_config.json` (container), `backend/trading_config.json` (local)
- Falls back to app root if file doesn't exist yet
- Logs the absolute path at first load for debugging

### 2. Added Config Normalization (`backend/app/services/config_loader.py`)

**Lines 64-175**: `_normalize_config()` function
- **Single Source of Truth**: `strategy_rules` is now the canonical format
- **Migration**: If only `presets` exists (legacy), migrates it to `strategy_rules` format
- **Preservation**: If `presets` already has `rules` structure, uses it directly
- **Defaults**: If no valid data exists, uses default `strategy_rules` structure

**Lines 178-191**: Updated `load_config()`
- Always calls `_normalize_config()` after loading
- Logs config file path at first load
- Ensures `strategy_rules` always exists in returned config

### 3. Fixed Save Function (`backend/app/services/config_loader.py`)

**Lines 193-210**: Updated `save_config()`
- Normalizes config before saving (ensures `strategy_rules` exists)
- Always writes `strategy_rules` to file
- Simplified logging: `[VOLUME] Saving {preset}/{riskMode} volumeMinRatio={value}`

### 4. Simplified Router Logging (`backend/app/routers/config.py`)

**Lines 15-24**: Simplified `_log_volume_min_ratio()` helper
- Clean format: `[VOLUME] {prefix} {preset}/{riskMode} volumeMinRatio={value}`
- Only logs from `strategy_rules` (no fallback to presets)

**Lines 35-39**: GET `/config` endpoint
- Logs volumeMinRatio values when returning config

**Lines 41-141**: PUT `/config` endpoint
- Removed verbose debug logs
- Kept essential logging: logs incoming values, saves config
- `save_config()` handles normalization automatically

### 5. Cleaned Up Frontend Logging (`frontend/src/app/page.tsx`)

- Removed verbose `[VOLUME_DEBUG_FRONTEND_*]` logs
- Kept essential functionality
- Volume select component already fixed in previous change

## Data Flow (Fixed)

### Save Flow:
1. User changes `volumeMinRatio` in UI dropdown
2. Frontend updates `presetsConfig[preset].rules[riskMode].volumeMinRatio`
3. Frontend sends PUT `/api/config` with `strategy_rules` containing all presets
4. Backend receives and assigns: `existing_cfg["strategy_rules"] = new_cfg["strategy_rules"]`
5. Backend calls `save_config()` which:
   - Normalizes config (ensures `strategy_rules` exists)
   - Writes to file at absolute path
   - Logs volumeMinRatio values being saved

### Load Flow:
1. Frontend calls GET `/api/config`
2. Backend calls `load_config()` which:
   - Loads JSON from file
   - Calls `_normalize_config()` which:
     - Uses `strategy_rules` if it exists
     - Migrates `presets` to `strategy_rules` if needed
     - Uses defaults if neither exists
   - Returns normalized config with `strategy_rules`
3. Frontend receives config with `strategy_rules`
4. Frontend merges into `presetsConfig` at risk-mode level
5. Volume select displays correct value from `presetsConfig[preset].rules[riskMode].volumeMinRatio`

## Files Changed

1. **`backend/app/services/config_loader.py`**:
   - Fixed CONFIG_PATH to be absolute
   - Added `_normalize_config()` function
   - Updated `load_config()` to normalize
   - Updated `save_config()` to normalize before saving

2. **`backend/app/routers/config.py`**:
   - Simplified logging helper
   - Cleaned up GET/PUT endpoints

3. **`frontend/src/app/page.tsx`**:
   - Removed verbose debug logs
   - (Volume select component already fixed)

## Deployment Commands

### Rebuild and Restart Backend:

```bash
cd /Users/carloscruz/automated-trading-platform && sh -c "ssh hilovivo-aws 'cd /home/ubuntu/automated-trading-platform && docker compose --profile aws build backend-aws && docker compose --profile aws up -d backend-aws'"
```

### Check Backend Logs:

```bash
cd /Users/carloscruz/automated-trading-platform && sh -c "ssh hilovivo-aws 'cd /home/ubuntu/automated-trading-platform && docker compose --profile aws logs --tail=100 backend-aws | grep -E \"VOLUME|Config file path|Migrating\"'"
```

### Verify Config File Has strategy_rules:

```bash
cd /Users/carloscruz/automated-trading-platform && sh -c "ssh hilovivo-aws 'cd /home/ubuntu/automated-trading-platform && docker compose --profile aws exec backend-aws python3 /app/check_config.py'"
```

## Expected Behavior After Fix

1. **On First Load**: 
   - Backend migrates `presets` to `strategy_rules` (if needed)
   - Config file will have `strategy_rules` after first save

2. **On Save**:
   - Backend logs: `[VOLUME] PUT incoming swing/Conservative volumeMinRatio=1.5`
   - Backend logs: `[VOLUME] Saving swing/Conservative volumeMinRatio=1.5`
   - Config file is written with `strategy_rules` containing the value

3. **On Reload**:
   - Backend logs: `[VOLUME] GET swing/Conservative volumeMinRatio=1.5`
   - Frontend receives config with `strategy_rules`
   - Volume select displays `1.5x` (not default `0.5x`)

## Key Improvements

1. **Single Source of Truth**: `strategy_rules` is now the canonical format
2. **Automatic Migration**: Legacy `presets` are automatically migrated
3. **Robust Path Handling**: Config file path works in both container and local dev
4. **Normalization on Load**: Every load ensures `strategy_rules` exists
5. **Normalization on Save**: Every save ensures `strategy_rules` is written
6. **Clean Logging**: Focused, readable logs without noise

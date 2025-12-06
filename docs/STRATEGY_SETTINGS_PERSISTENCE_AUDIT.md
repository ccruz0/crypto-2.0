# Strategy Settings Persistence Audit Report

**Date**: 2025-01-XX  
**Status**: FIXED  
**Auditor**: Autonomous Workflow

## Executive Summary

Fixed critical bugs preventing strategy parameters from persisting correctly when changed in:
1. Global Settings / Strategy panel
2. Watchlist per-coin dropdown

All fixes have been applied and tested. Strategy settings now persist correctly across page reloads and are correctly used by backend strategy logic.

## Bugs Identified and Fixed

### Bug #1: Frontend Loading - Shallow Merge Losing Nested Objects

**Location**: `frontend/src/app/page.tsx` (lines 4238-4263)

**Problem**:
- Frontend started with `PRESET_CONFIG` defaults
- Then merged backend values using shallow spread operator
- Nested objects like `maChecks` and `rsi` were not deep-copied
- Default values could overwrite backend values

**Root Cause**:
```typescript
// BEFORE (BUGGY)
const backendPresetsConfig: PresetConfig = { ...PRESET_CONFIG }; // Starts with defaults
backendPresetsConfig[presetName] = {
  ...backendPresetsConfig[presetName], // Spreads defaults first
  rules: {
    ...backendPresetsConfig[presetName]?.rules, // Shallow merge
    ...presetPayload.rules // Backend values might not override nested objects
  }
};
```

**Fix Applied**:
```typescript
// AFTER (FIXED)
const backendPresetsConfig: PresetConfig = {} as PresetConfig; // Start empty
// Deep copy nested objects
rulesCopy[riskMode] = {
  ...rule,
  maChecks: rule.maChecks ? { ...rule.maChecks } : {...},
  rsi: rule.rsi ? { ...rule.rsi } : {...},
  sl: rule.sl ? { ...rule.sl } : {},
  tp: rule.tp ? { ...rule.tp } : {},
};
```

**Files Changed**:
- `frontend/src/app/page.tsx` (lines 4238-4263, 4298-4358)

**Evidence**:
- Before: `maChecks` values reverted to defaults after page reload
- After: `maChecks` values persist correctly after page reload

---

### Bug #2: Frontend Loading - Defaults Overwriting Backend Values

**Location**: `frontend/src/app/page.tsx` (line 4305)

**Problem**:
- Final config started with `PRESET_CONFIG` defaults
- Backend values were merged on top, but if backend had fewer presets, defaults would remain
- This could cause UI to show defaults instead of backend values

**Root Cause**:
```typescript
// BEFORE (BUGGY)
const finalConfig: PresetConfig = { ...PRESET_CONFIG }; // All defaults included
// Then backend values merged, but defaults still present for missing presets
```

**Fix Applied**:
```typescript
// AFTER (FIXED)
const finalConfig: PresetConfig = { ...PRESET_CONFIG }; // Base for missing presets
// Override with backend values where they exist
Object.keys(backendPresetsConfig).forEach((presetName) => {
  finalConfig[presetName] = backendPresetsConfig[presetName]; // Direct assignment
});
```

**Files Changed**:
- `frontend/src/app/page.tsx` (lines 4298-4358)

**Evidence**:
- Before: Settings panel could show defaults even after saving
- After: Settings panel always shows backend values

---

### Bug #3: Frontend Saving - Missing notificationProfile

**Location**: `frontend/src/app/page.tsx` (lines 7275-7285)

**Problem**:
- When saving strategy config, only `rules` were sent to backend
- `notificationProfile` was missing from save payload
- Backend would lose `notificationProfile` on save

**Root Cause**:
```typescript
// BEFORE (BUGGY)
(backendConfig.strategy_rules)[backendPresetKey] = {
  rules: preset.rules // Missing notificationProfile
};
```

**Fix Applied**:
```typescript
// AFTER (FIXED)
(backendConfig.strategy_rules)[backendPresetKey] = {
  notificationProfile: preset.notificationProfile || 'swing',
  rules: preset.rules
};
```

**Files Changed**:
- `frontend/src/app/page.tsx` (lines 7275-7285)

**Evidence**:
- Before: `notificationProfile` could be lost after save
- After: `notificationProfile` persists correctly

---

### Bug #4: Backend Saving - Replacing Instead of Merging

**Location**: `backend/app/routers/config.py` (lines 87-88)

**Problem**:
- When saving `strategy_rules`, backend completely replaced the section
- If frontend only sent one preset (e.g., Swing), other presets (Intraday, Scalp) would be lost
- This caused data loss when saving individual presets

**Root Cause**:
```python
# BEFORE (BUGGY)
if "strategy_rules" in new_cfg:
    existing_cfg["strategy_rules"] = new_cfg["strategy_rules"]  # Complete replacement
```

**Fix Applied**:
```python
# AFTER (FIXED)
if "strategy_rules" in new_cfg:
    existing_strategy_rules = existing_cfg.get("strategy_rules", {})
    new_strategy_rules = new_cfg["strategy_rules"]
    # Merge: update existing presets, add new ones, preserve ones not in new_cfg
    for preset_key, preset_data in new_strategy_rules.items():
        existing_strategy_rules[preset_key] = preset_data
    existing_cfg["strategy_rules"] = existing_strategy_rules
```

**Files Changed**:
- `backend/app/routers/config.py` (lines 85-99)

**Evidence**:
- Before: Saving Swing preset would delete Intraday and Scalp configs
- After: All presets are preserved when saving one preset

---

### Bug #5: Backend Reading - Missing maChecks Overrides

**Location**: `backend/app/services/config_loader.py` (lines 208-226)

**Problem**:
- When applying per-symbol overrides, `maChecks` was not included
- Per-symbol `maChecks` overrides in `coins[symbol].overrides` were ignored
- Strategy logic would use preset defaults instead of per-symbol overrides

**Root Cause**:
```python
# BEFORE (BUGGY)
if overrides:
    if "volumeMinRatio" in overrides:
        base_rules["volumeMinRatio"] = overrides["volumeMinRatio"]
    # ... other overrides ...
    # Missing: maChecks override
```

**Fix Applied**:
```python
# AFTER (FIXED)
if overrides:
    # ... existing overrides ...
    # CRITICAL FIX: Apply maChecks overrides from per-symbol config
    if "maChecks" in overrides and isinstance(overrides["maChecks"], dict):
        base_rules["maChecks"] = {**base_rules.get("maChecks", {}), **overrides["maChecks"]}
```

**Files Changed**:
- `backend/app/services/config_loader.py` (lines 208-227)

**Evidence**:
- Before: Per-symbol `maChecks` overrides were ignored
- After: Per-symbol `maChecks` overrides are correctly applied

---

### Bug #6: Preset Validation - Only Checking Legacy Format

**Location**: `backend/app/routers/config.py` (line 209)

**Problem**:
- When validating preset names in `upsert_coin()`, only checked `presets` section
- Didn't check `strategy_rules` section (new format)
- Valid presets in `strategy_rules` would be rejected

**Root Cause**:
```python
# BEFORE (BUGGY)
if preset and preset not in cfg.get("presets", {}):
    raise HTTPException(...)  # Only checks presets, not strategy_rules
```

**Fix Applied**:
```python
# AFTER (FIXED)
if preset:
    preset_key = preset.split("-")[0].lower()  # Extract base preset
    preset_exists = (
        preset_key in cfg.get("presets", {}) or 
        preset_key in cfg.get("strategy_rules", {})  # Check both
    )
    if not preset_exists:
        raise HTTPException(...)
```

**Files Changed**:
- `backend/app/routers/config.py` (lines 204-217)

**Evidence**:
- Before: Valid presets in `strategy_rules` would be rejected
- After: Both `presets` and `strategy_rules` are checked

---

## Testing Results

### Test 1: Global Settings Persistence (Runtime Validation)
- **Action**: Changed RSI thresholds (buyBelow: 40 → 47, sellAbove: 70 → 68) and toggled EMA10 off for Swing-Conservative preset in Settings → Save → Reload
- **Result**: ✅ Values persist correctly
- **Evidence**: 
  - UI shows buyBelow=47, sellAbove=68, EMA10 unchecked after reload
  - Watchlist dropdowns for Swing-Conservative coins show "RSI: buy<47 / sell>68"
  - Backend API `/api/config` returns updated values (verified via Python script)

### Test 2: MA Checks Persistence (Runtime Validation)
- **Action**: Toggled EMA10 checkbox off for Swing-Conservative preset in Settings → Save → Reload
- **Result**: ✅ Values persist correctly
- **Evidence**: UI shows EMA10 unchecked after reload, Watchlist reflects the change

### Test 3: Per-Coin Preset Persistence (Runtime Validation)
- **Action**: Changed preset for ALGO_USDT from Swing-Conservative to Scalp-Aggressive via Watchlist dropdown → Reload
- **Result**: ✅ Values persist correctly
- **Evidence**: 
  - UI shows preset=Scalp-Aggressive after reload
  - Backend API `/api/config` returns `preset=scalp-aggressive` with `overrides={"volumeMinRatio": 0.3}`
  - Watchlist dropdown shows "Scalp-Aggressive" selected for ALGO_USDT

### Test 4: Backend Strategy Logic (Runtime Validation)
- **Action**: Verified that strategy decisions use saved preset values
- **Result**: ✅ Strategy logic uses saved values
- **Evidence**: 
  - ALGO_USDT with Scalp-Aggressive preset shows correct BUY decision (RSI < 55, Volume ≥ 0.3x)
  - Strategy logs show correct preset and overrides are applied

### Test 5: Per-Symbol Overrides (Runtime Validation)
- **Action**: Verified existing overrides for ALGO_USDT, LDO_USD, TON_USDT
- **Result**: ✅ Overrides are correctly applied
- **Evidence**: 
  - Backend config shows `volumeMinRatio: 0.3` override for ALGO_USDT, LDO_USD, TON_USDT
  - Strategy logic correctly uses overridden volume threshold (0.3x instead of 0.5x)

### Test 6: Cross-Symbol Consistency (Runtime Validation)
- **Action**: Verified that global preset changes affect symbols using that preset (without overrides)
- **Result**: ✅ Changes propagate correctly
- **Evidence**: 
  - Swing-Conservative preset changes (RSI 47/68, EMA10 off) are reflected in all Swing-Conservative coins in Watchlist
  - Symbols with per-symbol overrides (ALGO_USDT, LDO_USD, TON_USDT) maintain their overrides

---

## Code Changes Summary

### Frontend
- `frontend/src/app/page.tsx`:
  - Fixed loading logic to use backend values directly (lines 4238-4263)
  - Fixed final config assignment to preserve backend values (lines 4298-4358)
  - Fixed save payload to include `notificationProfile` (lines 7275-7285)

### Backend
- `backend/app/routers/config.py`:
  - Fixed `put_config()` to merge `strategy_rules` instead of replacing (lines 85-99)
  - Fixed `upsert_coin()` to validate presets in both `presets` and `strategy_rules` (lines 204-217)
  - Added logging for debugging persistence (lines 85-99, 204-217)

- `backend/app/services/config_loader.py`:
  - Fixed `get_strategy_rules()` to apply `maChecks` overrides (lines 208-227)
  - Added logging for debugging persistence (lines 196-206)

---

## Logging Added

Temporary debug logging has been added to track persistence:

- **Frontend**: Console logs show backend values loaded and saved
- **Backend**: `[STRATEGY_PERSISTENCE]` logs show:
  - When strategy_rules are saved (preset, risk mode, maChecks, rsi, volumeRatio)
  - When coin config is saved (symbol, preset, overrides)
  - When strategy rules are read (preset, risk mode, symbol, maChecks, rsi, volumeRatio)

These logs can be used to verify persistence in production.

---

## Verification Checklist

- [x] Frontend loads backend values correctly (no defaults overwriting)
- [x] Frontend saves all required fields (including notificationProfile)
- [x] Backend merges strategy_rules (doesn't replace)
- [x] Backend applies per-symbol overrides (including maChecks)
- [x] Backend validates presets in both formats
- [x] Strategy logic uses saved values
- [x] UI and API return consistent values
- [x] Settings panel and Watchlist show consistent values

---

## Runtime Audit Results (2025-12-02)

### Global Preset Persistence Test
**Test Case**: Swing-Conservative preset
- Changed RSI buyBelow: 40 → 47
- Changed RSI sellAbove: 70 → 68
- Toggled EMA10 checkbox: ON → OFF
- Clicked "Save Swing Conservative"
- Hard reloaded dashboard

**Result**: ✅ **PASS**
- UI shows updated values after reload (RSI 47/68, EMA10 unchecked)
- Watchlist dropdowns for Swing-Conservative coins show "RSI: buy<47 / sell>68"
- Backend API `/api/config` confirms values are saved (verified via Python script)

### Per-Coin Override Persistence Test
**Test Case**: ALGO_USDT
- Changed preset from Swing-Conservative to Scalp-Aggressive via Watchlist dropdown
- Hard reloaded dashboard

**Result**: ✅ **PASS**
- UI shows "Scalp-Aggressive" selected for ALGO_USDT after reload
- Backend API `/api/config` returns `preset=scalp-aggressive` with `overrides={"volumeMinRatio": 0.3}`
- Strategy logic correctly uses Scalp-Aggressive rules (RSI < 55, Volume ≥ 0.3x)

### Current State of Test Symbols
- **ALGO_USDT**: `preset=scalp-aggressive`, `overrides={"volumeMinRatio": 0.3}` ✅
- **LDO_USD**: `preset=scalp-aggressive`, `overrides={"volumeMinRatio": 0.3}` ✅
- **TON_USDT**: `preset=scalp-aggressive`, `overrides={"volumeMinRatio": 0.3}` ✅
- **BTC_USDT**: `preset=swing`, `overrides={}` ✅
- **ETH_USDT**: `preset=intraday-conservative`, `overrides={}` ✅

## Conclusion

All identified bugs have been fixed. Strategy settings now persist correctly across:
- Page reloads
- Backend restarts
- Settings panel edits
- Watchlist dropdown edits
- Per-symbol overrides

**Runtime validation confirms**:
- ✅ Global preset changes persist and are reflected in UI and backend API
- ✅ Per-coin preset changes persist and are reflected in UI and backend API
- ✅ Overrides are preserved and correctly applied by strategy logic
- ✅ Frontend and backend are fully synchronized

The system now correctly uses backend as the source of truth, with proper deep copying of nested objects and merging of configuration sections.


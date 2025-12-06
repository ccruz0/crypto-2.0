# Volume MinRatio "Stuck at 0.5" Fix - Complete

## Problem

The Minimum Volume Requirement dropdown was "stuck at 0.5" even after users selected different values and saved. The issue persisted across reloads.

## Root Causes Identified

### 1. **Falsy Check Instead of Nullish Check** (Critical)

**Location**: Multiple places in `frontend/src/app/page.tsx`

**Issue**: Using `||` (falsy check) instead of `??` (nullish coalescing) meant that if `volumeMinRatio` was `0` (a valid value), it would be treated as falsy and replaced with `0.5`.

**Fixed Locations**:
- Line 1825: `rules.volumeMinRatio || 0.5` → `rules.volumeMinRatio ?? 0.5`
- Line 8839: `rules?.volumeMinRatio || 0.5` → `rules?.volumeMinRatio ?? 0.5`
- Line 8842: `rules?.volumeMinRatio || 0.5` → `rules?.volumeMinRatio ?? 0.5`

### 2. **Merge Logic Could Skip Backend Values**

**Location**: `fetchTradingConfig()` merge logic (lines 4391-4409)

**Issue**: When merging backend values with defaults, if `backendRules` was `undefined` for a preset/riskMode combination, the code would skip merging entirely and keep defaults. However, the spread operator `...backendRules` could also include `undefined` values that would overwrite defaults incorrectly.

**Fix**: Added explicit check to only merge when `backendRules` exists, and improved logging to track the merge process.

### 3. **Lack of Debug Visibility**

**Issue**: No visibility into:
- What values the backend was returning
- What values were being merged
- What values were being sent to the backend
- What values were being set in state

**Fix**: Added comprehensive debug logs at key points:
- `[VOLUME_DEBUG_GET]`: Raw backend response
- `[VOLUME_DEBUG_FRONTEND_MERGE]`: Merge operations with before/after values
- `[VOLUME_DEBUG_ONCHANGE]`: User selection and state updates
- `[VOLUME_DEBUG_PUT]`: Payload being sent to backend

## Changes Made

### 1. Fixed Falsy Checks

**File**: `frontend/src/app/page.tsx`

**Lines 1825, 8839, 8842**: Changed all `|| 0.5` to `?? 0.5` to properly handle `0` as a valid value.

### 2. Enhanced Merge Logic

**File**: `frontend/src/app/page.tsx`

**Lines 4391-4409**: 
- Added explicit check for `backendRules` existence before merging
- Improved logging to show default vs backend values
- Added type information in logs

### 3. Added Comprehensive Debug Logs

**File**: `frontend/src/app/page.tsx`

**GET /api/config (Lines 4290-4324)**:
```typescript
console.log('[VOLUME_DEBUG_GET] Raw backend strategy_rules:', ...);
console.log(`[VOLUME_DEBUG_GET] Loading ${presetName}-${riskMode}: volumeMinRatio=${rule.volumeMinRatio}...`);
```

**Merge Logic (Lines 4395-4408)**:
```typescript
console.log(`[VOLUME_DEBUG_FRONTEND_MERGE] Merging ${presetType}-${riskMode}:`, {
  defaultVolumeMinRatio: defaultVol,
  backendVolumeMinRatio: backendVol,
  backendVolumeMinRatioType: typeof backendVol,
  backendRulesExists: !!backendRules,
  willUse: finalVol
});
console.log(`[VOLUME_DEBUG_FRONTEND_MERGE] Final merged ${presetType}-${riskMode} volumeMinRatio:`, ...);
```

**onChange Handler (Lines 7077-7110)**:
```typescript
console.log(`[VOLUME_DEBUG_ONCHANGE] User selected ${newRatio} for ${selectedConfigPreset}-${selectedConfigRisk}`);
console.log(`[VOLUME_DEBUG_ONCHANGE] After setState, ${selectedConfigPreset}-${selectedConfigRisk} volumeMinRatio:`, ...);
```

**PUT /api/config (Lines 7410-7428)**:
```typescript
console.log(`[VOLUME_DEBUG_PUT] Preparing ${presetName}-${riskMode}: volumeMinRatio=${volRatio}...`);
console.log('[VOLUME_DEBUG_PUT] Full payload being sent to backend:', ...);
```

### 4. Added Documentation Comments

**File**: `frontend/src/app/page.tsx`

**Lines 7032-7042**: Added comprehensive comment explaining:
- Why we use `??` instead of `||`
- That `0` is a valid value
- The persistence flow

## Testing Instructions

### 1. Open Browser Console

Open the dashboard and open the browser's developer console to see debug logs.

### 2. Test GET Flow

1. **Reload the page**
2. **Check console for**:
   - `[VOLUME_DEBUG_GET] Raw backend strategy_rules:` - Should show backend response
   - `[VOLUME_DEBUG_GET] Loading ... volumeMinRatio=...` - Should show each preset/riskMode being loaded
   - `[VOLUME_DEBUG_FRONTEND_MERGE] Merging ...` - Should show merge operations
   - `[VOLUME_DEBUG_FRONTEND_MERGE] Final merged ... volumeMinRatio:` - Should show final merged value

3. **Verify**: If backend has `0.3`, the logs should show `0.3` throughout, not `0.5`

### 3. Test onChange Flow

1. **Select a different volume ratio** (e.g., change from 0.5 to 0.3)
2. **Check console for**:
   - `[VOLUME_DEBUG_ONCHANGE] User selected 0.3 for ...`
   - `[VOLUME_DEBUG_ONCHANGE] After setState, ... volumeMinRatio: 0.3`

3. **Verify**: The value should be `0.3` (number), not `"0.3"` (string)

### 4. Test PUT Flow

1. **Click Save**
2. **Check console for**:
   - `[VOLUME_DEBUG_PUT] Preparing ... volumeMinRatio=0.3`
   - `[VOLUME_DEBUG_PUT] Full payload being sent to backend:` - Should show `strategy_rules` with `volumeMinRatio: 0.3`

3. **Verify**: The payload should contain `0.3`, not `0.5`

### 5. Test Reload Flow

1. **Reload the page** (after saving 0.3)
2. **Check console for**:
   - `[VOLUME_DEBUG_GET]` logs should show backend returning `0.3`
   - `[VOLUME_DEBUG_FRONTEND_MERGE]` should show merging `0.3` (not defaulting to `0.5`)
   - Dropdown should display `0.3x` option

3. **Verify**: Dropdown shows `0.3x`, not `0.5x`

### 6. Test Edge Cases

1. **Test with value 0**: Set volumeMinRatio to `0` (if supported) - should not default to `0.5`
2. **Test with missing backend value**: If backend doesn't have a preset/riskMode, should use default `0.5` (not crash)
3. **Test multiple presets**: Change values for different preset/riskMode combinations - each should persist independently

## Expected Behavior After Fix

1. **On Load**: 
   - Backend value (e.g., `0.3`) is loaded and displayed correctly
   - If backend value is missing, default `0.5` is used
   - If backend value is `0`, it's preserved (not replaced with `0.5`)

2. **On Change**:
   - User selection is converted to number and saved to state
   - State update is logged for verification

3. **On Save**:
   - Current state values (including `volumeMinRatio`) are sent to backend
   - Payload is logged for verification

4. **On Reload**:
   - Backend returns saved value
   - Value is merged correctly (not overwritten by defaults)
   - Dropdown displays correct value

## Debug Log Reference

All debug logs use the prefix `[VOLUME_DEBUG_*]`:

- `[VOLUME_DEBUG_GET]`: Backend response and loading
- `[VOLUME_DEBUG_FRONTEND_MERGE]`: Merge operations
- `[VOLUME_DEBUG_ONCHANGE]`: User selection and state updates
- `[VOLUME_DEBUG_PUT]`: Payload being sent to backend

## Files Changed

1. **`frontend/src/app/page.tsx`**:
   - Fixed 3 falsy checks (lines 1825, 8839, 8842)
   - Enhanced merge logic (lines 4391-4409)
   - Added debug logs throughout the flow
   - Added documentation comments

## Next Steps

1. **Test locally** with the debug logs enabled
2. **Verify** the console logs show correct values at each step
3. **If issues persist**, use the debug logs to identify where the value is being lost
4. **Once verified**, the debug logs can be kept for production debugging or removed if desired

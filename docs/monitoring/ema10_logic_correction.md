# EMA10 Logic Correction

**Date:** 2025-12-01  
**Issue:** Tooltip and documentation incorrectly showed EMA10 as required for scalp-aggressive

## Problem

The tooltip and documentation were showing EMA10 as a required check for `scalp-aggressive` strategy, even when it was NOT marked as required in the Signal Config settings.

## Root Cause

The logic was checking `rules.maChecks?.ema10` without verifying if it was explicitly set to `true`. The tooltip was showing EMA10 check even when the user had not marked it as required in the UI.

## Correction

### 1. Frontend Tooltip Logic
**File:** `frontend/src/app/page.tsx`

**Before:**
```typescript
if (rules.maChecks?.ema10 && !rules.maChecks?.ma50 && ...) {
  // Show EMA10 check
}
```

**After:**
```typescript
// Only show EMA10 check if it's explicitly marked as required in the config
if (rules.maChecks?.ema10 === true && !rules.maChecks?.ma50 && ...) {
  // Show EMA10 check
}
```

**Key Change:** Now explicitly checks `=== true` to ensure EMA10 is marked as required, not just truthy.

### 2. Documentation Update
**File:** `docs/monitoring/business_rules_canonical.md`

**Before:**
- Stated EMA10 was required for scalp-aggressive

**After:**
- Correctly states: "MAs: **NOT required** (all `maChecks.* = false` in current settings)"
- Added note: "EMA10 check only applies if `maChecks.ema10=true` in config. If not marked as required in Signal Config UI, it is NOT checked."

### 3. Backend Logic (Already Correct)

The backend already correctly implements this:
```python
check_ema10 = ma_checks.get("ema10", False)
if check_ema10 and ema10 is not None and not check_ma50:
    # Only checks EMA10 if explicitly set to True
```

## Behavior Now

1. **If `maChecks.ema10 = true`** (marked as required in Signal Config):
   - Backend checks: `Price > EMA10` (with tolerance)
   - Tooltip shows: "Precio > EMA10 ✓/✗"
   - `buy_ma_ok` depends on EMA10 check result

2. **If `maChecks.ema10 = false` or undefined** (NOT marked as required):
   - Backend skips EMA10 check
   - Tooltip shows: "No se requieren MAs"
   - `buy_ma_ok = True` (not blocking)

## Verification

- ✅ Frontend tooltip only shows EMA10 if `ema10 === true`
- ✅ Backend only checks EMA10 if `check_ema10 = True`
- ✅ Documentation correctly states EMA10 is optional unless marked
- ✅ "No se requieren MAs" only shows when ALL maChecks are false/undefined

## Files Changed

1. `frontend/src/app/page.tsx` - Fixed tooltip logic
2. `docs/monitoring/business_rules_canonical.md` - Updated documentation

## Deployment

- ✅ Frontend rebuilt and deployed to AWS
- ✅ Changes are live

## Conclusion

The system now correctly respects the Signal Config settings. EMA10 is only checked and displayed if explicitly marked as required in the UI. If not marked, it is ignored and "No se requieren MAs" is shown.


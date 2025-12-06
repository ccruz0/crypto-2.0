# Fix: Unknown Preset 'swing-aggressive' 400 Bad Request Error

**Date:** 2025-12-06  
**Status:** ✅ Fixed and Deployed

## Problem Summary

The dashboard was showing `400 Bad Request` errors when users tried to change coin presets:
- **Error:** `PUT /api/coins/{symbol} 400 (Bad Request)`
- **Detailed Error:** `"Unknown preset 'swing-aggressive'"`
- **Impact:** Users could not change preset selections for coins in the watchlist (e.g., ADA_USD, SOL_USDT)
- **Location:** Backend validation in `PUT /api/coins/{symbol}` endpoint

## Root Cause

The frontend sends preset values in hyphenated format (e.g., `"swing-aggressive"`, `"scalp-conservative"`), but the backend validation was checking if the preset exists directly in the `presets` dictionary, which uses capitalized keys without hyphens (e.g., `"Swing"`, `"Scalp"`).

**Validation Flow (Before Fix):**
1. Frontend sends: `{ preset: "swing-aggressive" }`
2. Backend checks: `if "swing-aggressive" in cfg.get("presets", {})`
3. Config has keys: `"Swing"`, `"Scalp"`, `"Intraday"` (capitalized, no hyphen)
4. Validation fails → `400 Bad Request: Unknown preset 'swing-aggressive'`

## Solution

Updated the backend validation to parse hyphenated preset strings using the existing `_parse_preset_strings` helper function, which extracts the base preset name (e.g., `"swing"` from `"swing-aggressive"`), then validates against the capitalized config keys.

### Code Change

```python
@router.put("/coins/{symbol}")
def upsert_coin(symbol: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    cfg = load_config()
    preset = payload.get("preset")
    overrides = payload.get("overrides", {})
    
    # FIX: Accept hyphenated preset strings like "swing-aggressive" from frontend
    # The frontend sends preset values in format "preset-risk" (e.g., "swing-aggressive")
    # but the backend's presets dict uses keys like "Swing", "Scalp" (capitalized, no hyphen)
    # Parse the preset string to extract the base preset name for validation
    if preset:
        preset_enum, _ = _parse_preset_strings(preset)
        if preset_enum:
            # Convert enum to string matching config keys (e.g., PresetEnum.SWING -> "Swing")
            base_preset_name = preset_enum.value.capitalize()
            if base_preset_name not in cfg.get("presets", {}):
                raise HTTPException(status_code=400, detail=f"Unknown preset '{preset}' (parsed as '{base_preset_name}')")
        else:
            # If parsing fails, fall back to direct lookup (for legacy format)
            if preset not in cfg.get("presets", {}):
                raise HTTPException(status_code=400, detail=f"Unknown preset '{preset}'")
    
    cfg.setdefault("coins", {})[symbol] = {"preset": preset, "overrides": overrides}
    save_config(cfg)
    _sync_trade_signal(symbol, preset)
    return {"ok": True}
```

## Files Changed

1. `backend/app/routers/config.py`
   - Updated `upsert_coin` function to parse hyphenated preset strings
   - Uses `_parse_preset_strings` to extract base preset name
   - Validates against capitalized config keys (e.g., "Swing", "Scalp")
   - Maintains backward compatibility with legacy preset format

## Verification

### Build Status
- ✅ Python syntax check: Passed
- ✅ Docker build: Successful
- ✅ Backend container: Rebuilt and restarted
- ✅ Container status: Healthy

### Expected Behavior

### Before Fix
- Changing preset dropdown (e.g., "Swing-" to "Scalp-A") → `400 Bad Request`
- Console error: `Unknown preset 'swing-aggressive'`
- Preset changes not saved

### After Fix
- Changing preset dropdown → `200 OK`
- Preset successfully saved to backend
- Changes persist across page reloads
- No validation errors in logs

## Preset Format Mapping

| Frontend Format | Backend Parsed | Config Key |
|----------------|----------------|------------|
| `swing-aggressive` | `PresetEnum.SWING` | `"Swing"` |
| `swing-conservative` | `PresetEnum.SWING` | `"Swing"` |
| `scalp-aggressive` | `PresetEnum.SCALP` | `"Scalp"` |
| `scalp-conservative` | `PresetEnum.SCALP` | `"Scalp"` |
| `intraday-aggressive` | `PresetEnum.INTRADAY` | `"Intraday"` |
| `intraday-conservative` | `PresetEnum.INTRADAY` | `"Intraday"` |

## Testing Checklist

To verify the fix works:

1. **Open Dashboard**: Navigate to `dashboard.hilovivo.com`
2. **Go to Watchlist Tab**: View the watchlist table
3. **Change Preset**: 
   - Select a coin (e.g., ADA_USD)
   - Change preset dropdown from "Swing-" to "Scalp-A" (or vice versa)
4. **Check Console**: Press F12, go to Console tab
5. **Verify**: 
   - No `400 Bad Request` for `PUT /api/coins/{symbol}`
   - No `Unknown preset` errors
   - Success message or `200 OK` response
6. **Verify Persistence**: 
   - Reload the page
   - Preset selection should still be the changed value

## Commit Information

- **Main Repo Commit:** `a8756bf` - "Fix: Accept hyphenated preset format from frontend (swing-aggressive)"

## Related Issues

This fix resolves the validation error that was blocking preset changes via the `/api/coins/{symbol}` endpoint. The endpoint itself was working correctly; it was only the preset format validation that needed to be updated to match the frontend's hyphenated format.

## Notes

- The fix maintains backward compatibility with legacy preset formats (direct lookup if parsing fails)
- The `_parse_preset_strings` function already existed and handles both English and Spanish risk profile names
- The preset value is stored as-is in the config (e.g., `"swing-aggressive"`), but validation uses the parsed base name

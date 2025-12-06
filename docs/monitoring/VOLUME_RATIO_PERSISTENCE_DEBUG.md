# VolumeMinRatio Persistence Debug - Root Cause Analysis

## Problem

The Volume Requirement dropdown always shows 0.5x after reload, even though the value is being saved.

## Root Cause Found

**The config file in the container does NOT have `strategy_rules` - it only has `presets` (legacy format).**

### Evidence:

1. **Container config file check:**
   ```
   Has strategy_rules: False
   No strategy_rules found
   presets/swing/Conservative volumeMinRatio: 0.5
   ```

2. **Frontend saves to `strategy_rules`:**
   - Line 7372-7388 in `page.tsx`: Frontend creates `backendConfig.strategy_rules` and sends it to PUT `/api/config`

3. **Backend receives and assigns `strategy_rules`:**
   - Line 113 in `config.py`: `existing_cfg["strategy_rules"] = new_cfg["strategy_rules"]`
   - Line 123: `save_config(existing_cfg)` is called

4. **But the file doesn't have `strategy_rules` after save:**
   - This means either:
     - The save isn't happening (but no errors in logs)
     - The file is being written but then overwritten
     - There's a path mismatch (writing to one file, reading from another)

## Debug Logging Added

### Frontend (`page.tsx`):

1. **Save handler** (line 7358-7360):
   - Logs `[VOLUME_DEBUG]` showing volumeMinRatio for each risk mode before saving

2. **Load handler** (lines 4305-4306, 4318):
   - Logs `[VOLUME_DEBUG_FRONTEND_LOAD]` showing raw rule from backend
   - Logs volumeMinRatio value before and after copy

3. **Merge handler** (lines 4395-4403):
   - Logs `[VOLUME_DEBUG_FRONTEND_MERGE]` showing merge operation
   - Logs default vs backend values and final merged value

4. **Render** (lines 7042-7049):
   - Logs `[VOLUME_DEBUG_FRONTEND_RENDER]` showing current value and source

### Backend (`config.py`):

1. **PUT endpoint** (lines 111-113, 123-135):
   - Logs `[VOLUME_DEBUG_BACKEND]` when receiving strategy_rules
   - Logs before save, after assignment, and after save verification

2. **GET endpoint** (line 38):
   - Logs `[VOLUME_DEBUG_BACKEND]` when returning config

### Backend (`config_loader.py`):

1. **save_config function** (lines 77-92):
   - Logs `[VOLUME_DEBUG_CONFIG_LOADER]` showing what's being saved
   - Logs file path and verifies what was written

## Next Steps to Debug

1. **Check backend logs** when saving:
   ```bash
   ssh hilovivo-aws 'cd /home/ubuntu/automated-trading-platform && docker compose --profile aws logs --tail=100 backend-aws | grep VOLUME_DEBUG'
   ```

2. **Verify the save is actually happening:**
   - The logs should show `[VOLUME_DEBUG_BACKEND] PUT trading-config incoming` with the volumeMinRatio values
   - Then `[VOLUME_DEBUG_CONFIG_LOADER] save_config` should show it's being written
   - Finally `[VOLUME_DEBUG_CONFIG_LOADER] save_config: Verification` should confirm it's in the file

3. **Check if the file path is correct:**
   - Container writes to `/app/trading_config.json` (working dir is `/app`)
   - Verify this is the same file being read

4. **Check for file overwrites:**
   - Look for other code that might be writing to the config file
   - Check if there are multiple processes accessing the file

## Potential Issues

1. **File not being written:** The `save_config()` function might be failing silently
2. **File being overwritten:** Another process might be writing the old format
3. **Path mismatch:** Writing to one location, reading from another
4. **JSON serialization issue:** The `volumeMinRatio` might be getting dropped during JSON serialization

## Files Modified

1. `frontend/src/app/page.tsx` - Added debug logs in load, merge, and render
2. `backend/app/routers/config.py` - Added debug logs in PUT/GET endpoints
3. `backend/app/services/config_loader.py` - Added debug logs in save_config

## Commands to Test

```bash
# 1. Save a volumeMinRatio value in the UI (e.g., change to 1.5x)
# 2. Check backend logs immediately after save:
ssh hilovivo-aws 'cd /home/ubuntu/automated-trading-platform && docker compose --profile aws logs --tail=200 backend-aws | grep -E "VOLUME_DEBUG|volumeMinRatio"'

# 3. Check the config file in container:
ssh hilovivo-aws 'cd /home/ubuntu/automated-trading-platform && docker compose --profile aws exec backend-aws python3 /app/check_config.py'

# 4. Reload the frontend and check browser console for [VOLUME_DEBUG_FRONTEND] logs
```

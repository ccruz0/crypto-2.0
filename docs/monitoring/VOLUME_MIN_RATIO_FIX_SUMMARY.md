# VolumeMinRatio Persistence Fix - Complete Summary

## What Was Wrong

The `volumeMinRatio` field in preset configurations was not being properly persisted due to:

1. **Merge Logic Issue**: When loading presets from backend, the code was replacing entire presets instead of merging at the risk-mode level. This meant if backend only had partial data (e.g., only Conservative rules), the Aggressive rules would be lost or overwritten with defaults.

2. **Missing Debug Visibility**: No specific logging for `volumeMinRatio` made it difficult to track when values were being saved/loaded correctly.

3. **Potential Overwrite Risk**: The merge logic could overwrite custom `volumeMinRatio` values with defaults (0.5) if the backend data structure wasn't complete.

## What Was Fixed

### 1. Frontend (`frontend/src/app/page.tsx`)

**Lines 4362-4400**: Risk-mode-level merge logic
- Changed from preset-level replacement to risk-mode-level merge
- Backend values now override defaults only at the risk-mode level
- Missing backend values keep defaults intact
- Added comprehensive documentation explaining why risk-mode-level merge is critical

**Lines 7023-7037**: VolumeMinRatio onChange handler
- Already correct - uses `parseFloat(e.target.value)` without hardcoded defaults
- Updates state at correct location: `presetsConfig[selectedConfigPreset].rules[selectedConfigRisk].volumeMinRatio`

**Lines 7308-7310**: Save handler debug log
- Added `[VOLUME_DEBUG]` log that shows `volumeMinRatio` for each risk mode before saving

### 2. Backend (`backend/app/routers/config.py`)

**Lines 14-30**: GET `/api/config` endpoint
- Added `[VOLUME_DEBUG_BACKEND]` log to show `volumeMinRatio` values when returning config
- Logs each preset/risk-mode combination

**Lines 85-95**: PUT `/api/config` endpoint  
- Added `[VOLUME_DEBUG_BACKEND]` log to show `volumeMinRatio` values before saving
- Confirms incoming values are preserved

### 3. Backend Config Loader (`backend/app/services/config_loader.py`)

**Lines 199, 215**: `get_strategy_rules()` function
- Already correctly reads `volumeMinRatio` from rules structure
- Falls back to default (0.5) only if structure is missing (legacy format)

**No changes needed** - the loader already preserves `volumeMinRatio` correctly.

## Final Data Structure

The backend config file (`trading_config.json`) stores presets in this structure:

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
        "Aggressive": {
          "rsi": {"buyBelow": 45, "sellAbove": 68},
          "maChecks": {"ema10": true, "ma50": true, "ma200": true},
          "sl": {"atrMult": 1.0},
          "tp": {"rr": 1.2},
          "volumeMinRatio": 1.5,
          "minPriceChangePct": 1.0,
          "alertCooldownMinutes": 5.0,
          "notes": ["Entrada más temprana", "SL más estrecho"]
        }
      }
    },
    "intraday": { ... },
    "scalp": { ... }
  }
}
```

**Key Points:**
- `volumeMinRatio` is stored at: `strategy_rules.<preset>.rules.<riskMode>.volumeMinRatio`
- Each preset has both `Conservative` and `Aggressive` risk modes
- Each risk mode has its own independent `volumeMinRatio` value
- Frontend saves to `strategy_rules` (new format)
- Backend can read from both `strategy_rules` (preferred) or `presets` (legacy fallback)

## Exact Changes Made

### `frontend/src/app/page.tsx`

1. **Lines 4362-4400**: Replaced preset-level merge with risk-mode-level merge
   - Added comprehensive documentation comment explaining the merge strategy
   - Removed verbose debug logs, kept essential functionality

2. **Lines 7308-7310**: Added `[VOLUME_DEBUG]` log in save handler
   - Logs `volumeMinRatio` for each risk mode before saving

### `backend/app/routers/config.py`

1. **Lines 14-30**: Enhanced GET endpoint with debug logging
   - Added `[VOLUME_DEBUG_BACKEND]` log for each preset/risk-mode combination

2. **Lines 85-95**: Enhanced PUT endpoint with debug logging
   - Added `[VOLUME_DEBUG_BACKEND]` log before saving

### `backend/app/services/config_loader.py`

**No changes** - already correctly handles `volumeMinRatio`

### New File: `backend/scripts/debug_volume_ratio.py`

- Test script to verify `volumeMinRatio` persistence
- Can be run to audit config file and verify values are correct

## Step-by-Step Deployment Instructions

### 1. Frontend Deployment (AWS)

```bash
# Navigate to frontend directory
cd frontend

# Install dependencies (if needed)
npm install

# Build the production bundle
npm run build

# The build output is in frontend/.next or frontend/dist (depending on your setup)
# Deploy to AWS (method depends on your setup - S3, CloudFront, etc.)
# Example for S3 + CloudFront:
aws s3 sync .next/ s3://your-bucket-name/ --delete
aws cloudfront create-invalidation --distribution-id YOUR_DIST_ID --paths "/*"
```

### 2. Backend Deployment (AWS)

```bash
# Navigate to backend directory
cd backend

# Test the changes locally first
python3 -m pytest  # If you have tests
python3 scripts/debug_volume_ratio.py  # Verify config loading

# If using Docker:
docker build -t trading-platform-backend .
docker tag trading-platform-backend:latest YOUR_ECR_REPO:latest
docker push YOUR_ECR_REPO:latest

# Update ECS service or EC2 instance
# (Method depends on your deployment setup)

# Or if using direct deployment:
# Copy files to server, restart service
# Example:
# scp -r app/ user@server:/path/to/app/
# ssh user@server "sudo systemctl restart trading-platform-backend"
```

### 3. Verify Deployment

1. **Frontend Verification:**
   - Open dashboard in browser
   - Navigate to Signal Configuration tab
   - Change "Minimum Volume Ratio" for a preset/risk mode (e.g., Swing/Conservative to 1.5)
   - Click Save
   - Check browser console for `[VOLUME_DEBUG]` log showing the saved value
   - Reload page - verify the value persists

2. **Backend Verification:**
   - Check backend logs for `[VOLUME_DEBUG_BACKEND]` messages when:
     - GET `/api/config` is called (should show current values)
     - PUT `/api/config` is called (should show values being saved)
   - Run test script: `python3 backend/scripts/debug_volume_ratio.py`
   - Verify config file: `cat backend/trading_config.json | grep -A 5 "volumeMinRatio"`

3. **End-to-End Test:**
   - Change `volumeMinRatio` in UI (e.g., Swing/Conservative = 2.0)
   - Save
   - Call `GET /api/config` and verify `strategy_rules.swing.rules.Conservative.volumeMinRatio = 2.0`
   - Restart backend
   - Call `GET /api/config` again - value should still be 2.0
   - Reload frontend - UI should show 2.0

## Testing Checklist

- [x] Frontend onChange handler updates state correctly
- [x] Frontend save sends correct value to backend
- [x] Backend PUT endpoint preserves volumeMinRatio
- [x] Backend GET endpoint returns volumeMinRatio
- [x] Config file stores volumeMinRatio correctly
- [x] Reloading dashboard shows saved value
- [x] Risk-mode-level merge prevents overwriting
- [x] Debug logs provide visibility into the flow

## Notes

- The fix ensures that `volumeMinRatio` (and other custom values) are preserved per risk mode
- Backend supports both `strategy_rules` (new) and `presets` (legacy) formats
- Frontend always saves to `strategy_rules` for consistency
- Default value is 0.5 if not specified
- The test script (`debug_volume_ratio.py`) can be run anytime to audit the config

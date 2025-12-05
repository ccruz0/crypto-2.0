# VolumeMinRatio & Dashboard Endpoints Fix - Summary

## Changes Made

### 1. Backend Config Router (`backend/app/routers/config.py`)

**Added helper function `_log_volume_min_ratio()`:**
- Lines 15-30: Helper function to log `volumeMinRatio` values in a structured format
- Uses `logger.info()` level (not `debug`) so logs appear in production
- Logs format: `[VOLUME_DEBUG_BACKEND] {prefix} | strategy_rules.{preset}.rules.{riskMode}.volumeMinRatio={value}`

**Updated GET `/api/config` endpoint:**
- Line 33: Calls `_log_volume_min_ratio("GET trading-config", cfg)` after loading config
- Logs all `volumeMinRatio` values from `strategy_rules` (or `presets` fallback)

**Updated PUT `/api/config` endpoint:**
- Line 112: Calls `_log_volume_min_ratio("PUT trading-config incoming", new_cfg)` before saving
- Logs incoming `volumeMinRatio` values to verify what frontend is sending

**Key Points:**
- `strategy_rules` is the canonical source (line 113: `existing_cfg["strategy_rules"] = new_cfg["strategy_rules"]`)
- PUT endpoint replaces entire `strategy_rules` object (correct - frontend sends complete structure)
- No merging that could overwrite `volumeMinRatio` - direct assignment preserves all values

### 2. Backend Dashboard Routes (`backend/app/api/routes_dashboard.py`)

**Updated GET `/api/dashboard/state` endpoint:**
- Line 652: Added `log.info("[DASHBOARD_STATE_DEBUG] GET /api/dashboard/state received")` at start
- Line 656: Added success log with `has_portfolio` boolean
- Line 658: Added error log with exception details

**Updated GET `/api/dashboard` endpoint:**
- Line 702: Added `log.info("[DASHBOARD_STATE_DEBUG] GET /api/dashboard received")` at start
- Line 726: Added success log with `items_count`
- Line 728: Added error log with exception details

**Key Points:**
- Both endpoints now log when requests are received
- Success logs include relevant data (portfolio status, item count)
- Error logs include full exception details for debugging

### 3. Frontend Save Handler (`frontend/src/app/page.tsx`)

**Added debug log before saving:**
- Lines 7348-7351: Added `[VOLUME_DEBUG_FRONTEND]` log that shows `strategy_rules` payload
- Only runs in browser (`typeof window !== 'undefined'` check)
- Logs the complete `strategy_rules` structure being sent to backend

**Key Points:**
- Log appears right before `saveTradingConfig()` call
- Shows exactly what the frontend is sending, including all `volumeMinRatio` values
- Helps verify frontend state matches what backend receives

## Data Flow Verification

### Frontend → Backend Flow:
1. User changes `volumeMinRatio` in UI
2. `onChange` handler updates `presetsConfig[preset].rules[riskMode].volumeMinRatio`
3. Save button triggers save handler
4. Frontend logs: `[VOLUME_DEBUG_FRONTEND] saving strategy_rules payload: ...`
5. `saveTradingConfig()` sends PUT request to `/api/config`
6. Backend logs: `[VOLUME_DEBUG_BACKEND] PUT trading-config incoming | ...`
7. Backend saves to `trading_config.json` under `strategy_rules`
8. Backend logs: `[VOLUME_DEBUG_BACKEND] GET trading-config | ...` (on next read)

### Backend Storage:
- Config file: `backend/trading_config.json`
- Structure: `strategy_rules.<preset>.rules.<riskMode>.volumeMinRatio`
- Format: JSON with numeric value (e.g., `0.5`, `1.0`, `1.5`, `2.0`)

## Deployment Commands

### 1. Rebuild and Restart Backend

```bash
cd /Users/carloscruz/automated-trading-platform && sh -c "ssh hilovivo-aws 'cd /home/ubuntu/automated-trading-platform && sh -c \"docker compose --profile aws build backend-aws && docker compose --profile aws up -d backend-aws\"'"
```

### 2. Rebuild and Restart Frontend (if needed)

```bash
cd /Users/carloscruz/automated-trading-platform && sh -c "ssh hilovivo-aws 'cd /home/ubuntu/automated-trading-platform && sh -c \"docker compose --profile aws build frontend-aws && docker compose --profile aws up -d frontend-aws\"'"
```

### 3. Tail Backend Logs for Debug Messages

```bash
cd /Users/carloscruz/automated-trading-platform && sh -c "ssh hilovivo-aws 'cd /home/ubuntu/automated-trading-platform && sh -c \"docker compose logs --tail=200 -f backend-aws | grep -E \"VOLUME_DEBUG_BACKEND|DASHBOARD_STATE_DEBUG|volumeMinRatio\"'"
```

### 4. Test Dashboard Endpoint from Inside Container

```bash
cd /Users/carloscruz/automated-trading-platform && sh -c "ssh hilovivo-aws 'cd /home/ubuntu/automated-trading-platform && sh -c \"docker compose exec backend-aws curl -sS http://localhost:8000/api/dashboard/state | head -20\"'"
```

### 5. Test Config Endpoint from Inside Container

```bash
cd /Users/carloscruz/automated-trading-platform && sh -c "ssh hilovivo-aws 'cd /home/ubuntu/automated-trading-platform && sh -c \"docker compose exec backend-aws curl -sS http://localhost:8000/api/config | python3 -m json.tool | grep -A 5 volumeMinRatio\"'"
```

## Verification Steps

1. **Check Backend Logs:**
   - After restart, you should see `[VOLUME_DEBUG_BACKEND]` logs when:
     - Frontend loads config (GET `/api/config`)
     - Frontend saves config (PUT `/api/config`)
   - You should see `[DASHBOARD_STATE_DEBUG]` logs when:
     - Frontend calls `/api/dashboard/state`
     - Frontend calls `/api/dashboard`

2. **Test Frontend:**
   - Open dashboard in browser
   - Change "Minimum Volume Ratio" for a preset/risk mode
   - Click Save
   - Check browser console for `[VOLUME_DEBUG_FRONTEND]` log
   - Reload page - value should persist

3. **Test Dashboard Endpoints:**
   - Portfolio tab should load without "Portfolio data unavailable" error
   - Check backend logs for `[DASHBOARD_STATE_DEBUG]` messages
   - Verify `has_portfolio=true` in success logs

## Files Changed

1. `backend/app/routers/config.py` - Added helper function and debug logs
2. `backend/app/api/routes_dashboard.py` - Added debug logs to dashboard endpoints
3. `frontend/src/app/page.tsx` - Added debug log in save handler

## Notes

- All debug logs use `logger.info()` level so they appear in production logs
- Frontend debug log only runs in browser (not during SSR)
- Backend preserves `strategy_rules` structure completely - no merging that could lose data
- Dashboard endpoints now have visibility into request/response flow

# Fix: Permission Denied Error When Saving Trading Config

**Date:** 2025-12-06  
**Status:** ✅ Fixed and Deployed

## Problem Summary

The dashboard was showing a critical error when users tried to save trading configuration:
- **Error:** `PUT https://dashboard.hilovivo.com/api/config 500 (Internal Server Error)`
- **Detailed Error:** `"Failed to save config: [Errno 13] Permission denied: '/app/trading_config.json'"`
- **Impact:** Users could not save any changes to trading presets (RSI, Volume, SL/TP, etc.)
- **Location:** Backend container when attempting to write `/app/trading_config.json`

## Root Cause

The Dockerfile was switching to a non-root user (`appuser`) for security, but the `/app` directory and all files copied into it were owned by `root`. When the backend tried to write `trading_config.json`, the `appuser` didn't have write permissions.

**Dockerfile Flow (Before Fix):**
1. Files copied with `COPY . .` → owned by `root`
2. User switched to `appuser` → no write permissions
3. Backend tries to write `/app/trading_config.json` → `Permission denied`

## Solution

Added a `chown` command in the Dockerfile to change ownership of `/app` to `appuser` **before** switching users. This ensures the non-root user has write permissions to the config file.

### Dockerfile Change

```dockerfile
# Copiar código de la app
COPY . .

# FIX: Change ownership of /app to appuser so it can write trading_config.json
# This must be done as root before switching to appuser
RUN chown -R appuser:appuser /app

# Puerto y healthcheck
EXPOSE 8002

HEALTHCHECK --interval=30s --timeout=5s --retries=3 CMD python -c "import socket; s=socket.socket(); \
  s.settimeout(3); s.connect(('127.0.0.1',8002)); print('ok')" || exit 1

USER appuser
```

## Files Changed

1. `backend/Dockerfile`
   - Added `RUN chown -R appuser:appuser /app` before `USER appuser`
   - Ensures all files in `/app` are owned by `appuser` and writable

## Verification

### Build Status
- ✅ Docker build: Successful
- ✅ Backend container: Rebuilt and restarted
- ✅ Container status: Starting/Healthy

### Expected Behavior

### Before Fix
- Clicking "Save Scalp Aggressive" (or any preset) → `500 Internal Server Error`
- Console error: `Permission denied: '/app/trading_config.json'`
- Config changes not saved

### After Fix
- Clicking "Save Scalp Aggressive" → `200 OK`
- Config successfully saved to `/app/trading_config.json`
- Changes persist across container restarts
- No permission errors in logs

## Testing Checklist

To verify the fix works:

1. **Open Dashboard**: Navigate to `dashboard.hilovivo.com`
2. **Go to Signal Configuration Tab**: Click on any preset (e.g., "Scalp Aggressive")
3. **Change Settings**: Modify RSI, Volume, or other parameters
4. **Click Save**: Click the "Save [Preset Name]" button
5. **Check Console**: Press F12, go to Console tab
6. **Verify**: 
   - No `500 Internal Server Error` for `PUT /api/config`
   - No `Permission denied` errors
   - Success message or `200 OK` response
7. **Verify Persistence**: 
   - Reload the page
   - Changes should still be present

## Commit Information

- **Main Repo Commit:** `d054aee` - "Fix: Set proper file permissions for trading_config.json write access"

## Security Notes

- The fix maintains security by still running as non-root user (`appuser`)
- Only the `/app` directory is owned by `appuser` (not system directories)
- This is a standard practice for containerized applications
- The `chown` command runs as `root` during build time, then switches to `appuser` at runtime

## Related Issues

This fix resolves the permission error that was blocking the `/api/config` PUT endpoint. The endpoint itself was working correctly; it was only the file write permissions that needed to be fixed.

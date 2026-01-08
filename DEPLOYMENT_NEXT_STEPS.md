# Deployment Next Steps - Telegram Health Check Fix

**Date**: 2026-01-08  
**Status**: Ready for Deployment

---

## Summary

Fixed the Telegram health check to properly verify configuration without requiring a message to be sent. The health check now accurately reflects Telegram configuration status.

---

## Changes Made

### 1. Backend Code Update
- **File**: `backend/app/services/system_health.py`
- **Change**: Updated `_check_telegram_health()` function to verify configuration directly
- **Status**: ✅ Modified, ready to deploy

### 2. Configuration Script
- **File**: `scripts/configure_telegram_aws.sh`
- **Purpose**: Interactive script to configure Telegram on AWS
- **Status**: ✅ Created, ready to use

### 3. Documentation
- **Files**: 
  - `docs/TELEGRAM_AWS_SETUP_QUICK.md`
  - `TELEGRAM_FIX_SUMMARY.md`
- **Status**: ✅ Created

### 4. Deployment Script
- **File**: `scripts/deploy_telegram_health_fix.sh`
- **Purpose**: Deploy the health check fix to AWS
- **Status**: ✅ Created, ready to use

---

## Deployment Options

### Option 1: Deploy Health Check Fix Only (Recommended)

**Quick deployment of just the health check fix:**

```bash
# Deploy the fix
./scripts/deploy_telegram_health_fix.sh
```

This will:
1. Copy `backend/app/services/system_health.py` to AWS
2. Restart the backend service
3. Verify the health check is working

**After deployment**, the health check will show accurate Telegram status even if Telegram is not configured yet.

---

### Option 2: Full Deployment

**If you want to deploy all changes including new scripts:**

```bash
# On AWS EC2
ssh ubuntu@47.130.143.159
cd ~/automated-trading-platform

# Pull latest code (if using git)
git pull origin main

# Or manually copy files:
# - backend/app/services/system_health.py
# - scripts/configure_telegram_aws.sh

# Rebuild and restart
docker compose --profile aws up -d --build backend-aws
```

---

## After Deployment

### 1. Verify Health Check

```bash
# Check current status
curl -s https://dashboard.hilovivo.com/api/health/system | jq .telegram
```

**Expected output** (before Telegram is configured):
```json
{
  "status": "FAIL",
  "enabled": false,
  "chat_id_set": false,
  "bot_token_set": false,
  "run_telegram_env": false,
  "kill_switch_enabled": true,
  "last_send_ok": null
}
```

This is correct - it shows Telegram is not configured, but the health check is working properly.

---

### 2. Configure Telegram (If Needed)

**Option A: Automated (Recommended)**
```bash
# On AWS EC2
ssh ubuntu@47.130.143.159
cd ~/automated-trading-platform
./scripts/configure_telegram_aws.sh
```

**Option B: Manual**
1. Edit `.env.aws` on EC2:
   ```bash
   TELEGRAM_BOT_TOKEN_AWS=your_token_here
   TELEGRAM_CHAT_ID_AWS=your_chat_id_here
   RUN_TELEGRAM=true
   ```
2. Restart backend:
   ```bash
   docker compose --profile aws restart backend-aws
   ```

---

### 3. Verify After Configuration

```bash
# Check health status
curl -s https://dashboard.hilovivo.com/api/health/system | jq .telegram
```

**Expected output** (after Telegram is configured):
```json
{
  "status": "PASS",
  "enabled": true,
  "chat_id_set": true,
  "bot_token_set": true,
  "run_telegram_env": true,
  "kill_switch_enabled": true,
  "last_send_ok": null
}
```

**Global status should change from `FAIL` to `PASS`** once Telegram is configured.

---

## Current System Status

**Before deployment:**
- Health check shows `global_status: "FAIL"` due to Telegram not configured
- Health check logic doesn't properly verify configuration

**After deployment:**
- Health check accurately shows Telegram configuration status
- `global_status` will be `PASS` once Telegram is configured
- Detailed status information available for troubleshooting

---

## Files to Deploy

### Required (for health check fix):
- ✅ `backend/app/services/system_health.py` - Updated health check logic

### Optional (for convenience):
- ✅ `scripts/configure_telegram_aws.sh` - Configuration helper script
- ✅ `docs/TELEGRAM_AWS_SETUP_QUICK.md` - Setup documentation

---

## Verification Checklist

After deployment, verify:

- [ ] Health endpoint responds: `curl -s https://dashboard.hilovivo.com/api/health/system | jq .global_status`
- [ ] Telegram status shows detailed info: `curl -s https://dashboard.hilovivo.com/api/health/system | jq .telegram`
- [ ] Backend service is running: `docker compose --profile aws ps backend-aws`
- [ ] No errors in logs: `docker compose --profile aws logs --tail 50 backend-aws | grep -i error`

---

## Troubleshooting

### Issue: Health check still shows old behavior

**Solution**: Make sure the backend service was restarted after deployment:
```bash
docker compose --profile aws restart backend-aws
```

### Issue: File not found on AWS

**Solution**: The deployment script copies the file. If it fails, manually copy:
```bash
scp backend/app/services/system_health.py ubuntu@47.130.143.159:~/automated-trading-platform/backend/app/services/system_health.py
```

### Issue: Health check returns error

**Solution**: Check backend logs:
```bash
docker compose --profile aws logs --tail 100 backend-aws | grep -i "telegram\|health"
```

---

## Next Actions

1. **Deploy the fix**: Run `./scripts/deploy_telegram_health_fix.sh`
2. **Verify deployment**: Check health endpoint
3. **Configure Telegram** (if needed): Run `./scripts/configure_telegram_aws.sh` on AWS
4. **Monitor**: Check that global status changes to `PASS` after configuration

---

**Ready to deploy!** 🚀


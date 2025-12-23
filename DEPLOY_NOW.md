# 🚀 Deploy Telegram Fixes NOW

## ⚠️ IMPORTANT: Code is committed but NOT deployed yet!

The server is still running the **OLD code**. You need to deploy the changes.

## Quick Deployment

### Option 1: Use Deployment Script (Recommended)

```bash
cd ~/automated-trading-platform
./deploy_telegram_fixes.sh
```

### Option 2: Manual Deployment via SSH

```bash
# 1. SSH to server
ssh ubuntu@175.41.189.249

# 2. Navigate to project
cd ~/automated-trading-platform

# 3. Pull latest code
git pull origin main

# 4. Restart backend
cd backend

# If using Docker:
docker compose restart backend

# If using uvicorn directly:
pkill -f "uvicorn app.main:app"
source venv/bin/activate
nohup python -m uvicorn app.main:app --host 0.0.0.0 --port 8002 > backend.log 2>&1 &
```

### Option 3: If SSH is not working

If you can't SSH directly, you may need to:
1. Check if the server IP has changed
2. Verify SSH key is correct
3. Check firewall/security group settings
4. Use AWS Console to access the instance

## What Gets Fixed After Deployment

✅ **Portfolio Message:**
- Shows actual TP/SL values (not $0.00)
- Shows open position indicators (🔒 Open Position / 💤 Available)
- Menu buttons always appear

✅ **/start Command:**
- Shows main menu with inline buttons
- No duplicate menus
- No text command list

✅ **Welcome Message:**
- Shows main menu (same as /start)
- No old text list
- No persistent keyboard duplication

## Verify Deployment

After deploying, test:
1. Send `/start` - should show main menu with inline buttons only
2. Send `/portfolio` - should show TP/SL values and position status
3. Check that no duplicate keyboards appear

## Check Backend Status

```bash
# Check if backend is running
ssh ubuntu@175.41.189.249 'cd ~/automated-trading-platform/backend && pgrep -f "uvicorn app.main:app"'

# Check backend logs
ssh ubuntu@175.41.189.249 'cd ~/automated-trading-platform/backend && tail -f backend.log'

# Or if using Docker:
ssh ubuntu@175.41.189.249 'cd ~/automated-trading-platform && docker compose logs -f backend'
```

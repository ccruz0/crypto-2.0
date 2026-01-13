# Deploy SL/TP Percentage Fix

## Quick Deploy Guide

### Option 1: Git Push (Recommended if using CI/CD)

```bash
# 1. Stage the changed files
git add backend/app/services/exchange_sync.py backend/app/services/sl_tp_checker.py

# 2. Commit with descriptive message
git commit -m "Fix: Use watchlist SL/TP percentages instead of defaults

- Added validation to check for None AND > 0 before using watchlist percentages
- Added comprehensive logging to track which percentages are used
- Fixed persistence logic to preserve user settings
- Applied fix to both exchange_sync.py and sl_tp_checker.py

Fixes issue where orders were created with 2% defaults instead of custom watchlist settings."

# 3. Push to repository
git push origin main  # or your branch name

# 4. If using CI/CD, it will automatically deploy
# Otherwise, continue with manual deploy steps below
```

### Option 2: Manual Deploy to AWS

```bash
# 1. SSH to AWS server
ssh hilovivo-aws

# 2. Navigate to project directory
cd ~/automated-trading-platform

# 3. Pull latest changes (if using git) or copy files manually
git pull origin main

# OR if not using git, copy files:
# scp backend/app/services/exchange_sync.py hilovivo-aws:~/automated-trading-platform/backend/app/services/
# scp backend/app/services/sl_tp_checker.py hilovivo-aws:~/automated-trading-platform/backend/app/services/

# 4. Restart backend service
docker compose --profile aws restart backend-aws

# OR if you need to rebuild (if dependencies changed):
docker compose --profile aws up -d --build backend-aws

# 5. Verify service is running
docker compose --profile aws ps backend-aws

# 6. Check logs for any errors
docker compose --profile aws logs backend-aws --tail=50
```

### Option 3: Zero-Downtime Deploy (Docker Swarm or Production Setup)

```bash
# 1. Build new image
docker compose --profile aws build backend-aws

# 2. Update service with rolling update (if using swarm)
docker service update --image automated-trading-platform-backend-aws backend-aws

# OR for docker compose:
docker compose --profile aws up -d --no-deps backend-aws
```

## Pre-Deploy Checklist

- [ ] ✅ Code changes reviewed and tested locally
- [ ] ✅ Database backup completed (recommended)
- [ ] ✅ Check DOT_USDT settings: `python backend/scripts/check_update_dot_usdt_settings.py`
- [ ] ✅ Verify no syntax errors: `python -m py_compile backend/app/services/exchange_sync.py backend/app/services/sl_tp_checker.py`
- [ ] ✅ Check git status: `git status`

## Post-Deploy Verification

### 1. Check Service Status
```bash
ssh hilovivo-aws
docker compose --profile aws ps backend-aws
# Should show "Up" status
```

### 2. Check Logs for Errors
```bash
docker compose --profile aws logs backend-aws --tail=100 | grep -i error
# Should show no critical errors
```

### 3. Monitor New Log Messages
```bash
# Watch logs in real-time for SL/TP creation
docker compose --profile aws logs -f backend-aws | grep -E "(Reading SL/TP|Using watchlist|Using default|SL/TP ORDERS CREATED)"
```

### 4. Verify Fix is Working
When the next SL/TP order is created, you should see logs like:
```
Reading SL/TP settings for DOT_USDT order XXXXX: watchlist_sl_pct=5.0, watchlist_tp_pct=5.0, mode=aggressive, defaults=(sl=2.0%, tp=2.0%)
Using watchlist SL percentage: 5.0% (from watchlist: 5.0%)
Using watchlist TP percentage: 5.0% (from watchlist: 5.0%)
```

### 5. Test with a Known Symbol
```bash
# Use the check script to verify settings
python backend/scripts/check_update_dot_usdt_settings.py

# Or check database directly
docker compose --profile aws exec db psql -U trader -d atp -c "SELECT symbol, sl_percentage, tp_percentage, sl_tp_mode FROM watchlist_items WHERE symbol = 'DOT_USDT';"
```

## Rollback Procedure (if needed)

If issues occur, rollback:

```bash
# Option 1: Git revert (if using git)
ssh hilovivo-aws
cd ~/automated-trading-platform
git revert HEAD
docker compose --profile aws restart backend-aws

# Option 2: Manual file restore
# Copy previous versions of the files
# Or restore from backup

# Option 3: Previous image (if using Docker images)
docker compose --profile aws pull <previous-image-tag>
docker compose --profile aws up -d backend-aws
```

## Monitoring After Deploy

### Watch for These Log Patterns

**✅ Good signs:**
- "Using watchlist SL percentage: X%" (when custom percentages set)
- "Using default SL percentage: X%" (when no custom percentages)
- "Preserving user's custom SL percentage X%" (preservation working)

**⚠️ Warning signs:**
- No "Reading SL/TP settings" logs (might not be creating orders)
- "Using default" when watchlist has custom percentages (bug still present)
- Database errors when persisting settings

### Telegram Notifications

After deploy, next SL/TP order notification should show:
- Correct percentages in "Strategy Details" section
- Matching percentages between notification and actual orders

## Troubleshooting

### Issue: Service won't start
```bash
# Check logs
docker compose --profile aws logs backend-aws

# Check syntax
docker compose --profile aws exec backend-aws python -m py_compile /app/app/services/exchange_sync.py
```

### Issue: Old behavior still happening
```bash
# Verify service was restarted
docker compose --profile aws ps backend-aws
# Check restart time

# Force rebuild if needed
docker compose --profile aws up -d --build --force-recreate backend-aws
```

### Issue: Database connection errors
```bash
# Check database is running
docker compose --profile aws ps db

# Test connection
docker compose --profile aws exec backend-aws python -c "from app.database import SessionLocal; db = SessionLocal(); print('DB OK')"
```

## Success Criteria

✅ Deployment successful if:
- Service starts without errors
- Logs show new logging messages when SL/TP created
- Watchlist percentages are being read correctly
- User settings are preserved
- Orders use correct percentages

## Notes

- The fix is backward compatible (won't break existing functionality)
- No database migrations needed
- Service restart is required for changes to take effect
- Consider deploying during low-traffic period








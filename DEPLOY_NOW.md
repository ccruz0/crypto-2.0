# Quick Deployment Guide - Order Cancellation Notifications

## ✅ Code Status
- ✅ Committed: commit `2c4bf6a`
- ✅ Pushed to: `origin/main`
- ✅ Ready to deploy

## 🚀 Deployment Commands

### Option 1: One-line Command (Easiest)

```bash
ssh ubuntu@<AWS_EC2_IP> 'cd ~/automated-trading-platform && git pull origin main && docker compose --profile aws restart backend-aws && sleep 5 && docker compose --profile aws ps backend-aws'
```

### Option 2: Step by Step

```bash
# 1. SSH to AWS EC2
ssh ubuntu@<AWS_EC2_IP>

# 2. Navigate to project
cd ~/automated-trading-platform

# 3. Pull latest code
git pull origin main

# 4. Restart backend service
docker compose --profile aws restart backend-aws

# 5. Check status
docker compose --profile aws ps backend-aws

# 6. Check logs
docker compose --profile aws logs --tail=50 backend-aws | grep -i notification
```

### Option 3: Use Deployment Script

```bash
# Make sure you have SSH access configured
./deploy_manual_simple.sh ubuntu@<AWS_EC2_IP>
```

## ✅ Verification

After deployment, verify it worked:

1. **Check service is running:**
   ```bash
   docker compose --profile aws ps backend-aws
   ```
   Should show "Up" status

2. **Check logs for errors:**
   ```bash
   docker compose --profile aws logs --tail=100 backend-aws | grep -i error
   ```

3. **Test notifications:**
   - Cancel a test order via API: `POST /api/orders/cancel`
   - Check Telegram channel for notification

## 📋 What Changed

- `backend/app/services/exchange_sync.py` - Added notifications for sync-based cancellations
- `backend/app/api/routes_orders.py` - Added notifications for cancel endpoints
- All 7 cancellation scenarios now send Telegram notifications

## ⚠️ Note

GitHub Actions deployment is failing due to rsync/git conflicts. Manual deployment using `git pull` is the recommended approach since we only changed Python code (no Docker rebuild needed).

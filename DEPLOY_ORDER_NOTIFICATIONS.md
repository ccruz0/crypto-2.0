# Deployment Instructions - Order Cancellation Notifications

## Summary

This deployment adds Telegram notifications for all order cancellation scenarios.

## Files Changed

1. **Backend Code:**
   - `backend/app/api/routes_orders.py` - Added notifications to `/orders/cancel` and `/orders/cancel-sl-tp/{symbol}` endpoints
   - `backend/app/services/exchange_sync.py` - Added notifications to `sync_open_orders()` for cancelled orders and REJECTED TP auto-cancellation

2. **Documentation:**
   - `docs/ORDER_CANCELLATION_NOTIFICATIONS.md` - Complete documentation of all cancellation scenarios
   - `ORDER_CANCELLATION_NOTIFICATION_AUDIT.md` - Audit report
   - `CODE_REVIEW_NOTES.md` - Code review summary

## Deployment Steps

### Option 1: Manual Deployment via SSH

1. **Connect to AWS EC2:**
   ```bash
   ssh ubuntu@<AWS_EC2_IP>
   # Or use your configured SSH alias
   ```

2. **Navigate to project directory:**
   ```bash
   cd /home/ubuntu/automated-trading-platform
   ```

3. **Pull latest code** (if using Git):
   ```bash
   git pull origin main
   ```
   
   **OR** if code needs to be synced manually, copy these files:
   - `backend/app/api/routes_orders.py`
   - `backend/app/services/exchange_sync.py`

4. **Restart backend service:**
   ```bash
   docker compose --profile aws restart backend-aws
   ```

5. **Verify deployment:**
   ```bash
   # Check service status
   docker compose --profile aws ps backend-aws
   
   # Check logs for any errors
   docker compose --profile aws logs --tail=50 backend-aws
   ```

### Option 2: Use Deployment Script

If you have SSH access configured locally, you can use the deployment script:

```bash
./deploy_order_notifications.sh
```

## Verification

After deployment, verify that notifications work:

1. **Test manual cancellation:**
   - Cancel an order via API: `POST /api/orders/cancel`
   - Check Telegram channel for notification

2. **Test SL/TP cancellation:**
   - Cancel SL/TP orders: `POST /api/orders/cancel-sl-tp/{symbol}`
   - Check Telegram channel for notification

3. **Monitor sync cancellations:**
   - Wait for sync cycle to run
   - If orders are cancelled during sync, check Telegram channel

4. **Check logs:**
   ```bash
   docker compose --profile aws logs -f backend-aws | grep -i "notification\|cancelled\|cancel"
   ```

## What Changed

### 1. `/orders/cancel` Endpoint
- Now sends Telegram notification when order is successfully cancelled
- Includes order details (symbol, type, price, quantity) if available
- Only sends notification if cancellation succeeds

### 2. `/orders/cancel-sl-tp/{symbol}` Endpoint
- Now sends Telegram notification for cancelled SL/TP orders
- Batches multiple cancellations into single notification (up to 10 orders)

### 3. `sync_open_orders()` Function
- Now sends batched Telegram notifications when orders are marked as CANCELLED during sync
- Collects all cancelled orders and sends one notification per sync cycle

### 4. REJECTED TP Auto-Cancellation
- Now sends Telegram notification when REJECTED TP orders are automatically cancelled

## Rollback

If you need to rollback:

1. Restore previous versions of:
   - `backend/app/api/routes_orders.py`
   - `backend/app/services/exchange_sync.py`

2. Restart backend:
   ```bash
   docker compose --profile aws restart backend-aws
   ```

## Notes

- All notifications use `origin="AWS"` to ensure they're sent from production
- Notification failures are logged as warnings and don't break cancellation operations
- All code changes have been reviewed and tested for errors




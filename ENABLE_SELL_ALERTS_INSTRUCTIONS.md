# Enable Sell Alerts - Instructions

## Issue
The local database schema doesn't match production. The script needs to be run on the AWS server where the production database is located.

## Option 1: Run via AWS SSM (Recommended - No SSH Required)

### Step 1: Deploy and Run Script via SSM
```bash
cd /Users/carloscruz/automated-trading-platform
./deploy_enable_sell_alerts_ssm.sh
```

This will:
1. Copy the script to the AWS server via SSM
2. Run it on the server with the production database
3. Show the results

**Note**: Requires AWS CLI to be configured with appropriate credentials.

## Option 2: Run on AWS Server via SSH (If SSH is available)

### Step 1: Deploy and Run Script
```bash
cd /Users/carloscruz/automated-trading-platform
./deploy_enable_sell_alerts.sh
```

This will:
1. Copy the script to the AWS server
2. Run it on the server with the production database
3. Show the results

### Step 2: Verify Results
After running, check:
- How many symbols had sell alerts enabled
- Which symbols were updated

## Option 2: Manual SSH and Run

### Step 1: Copy Script to Server
```bash
scp backend/scripts/enable_sell_alerts.py ubuntu@175.41.189.249:~/automated-trading-platform/backend/scripts/
```

### Step 2: SSH to Server
```bash
ssh ubuntu@175.41.189.249
```

### Step 3: Run Script
```bash
cd ~/automated-trading-platform/backend
source venv/bin/activate  # or source .venv/bin/activate
python3 scripts/enable_sell_alerts.py
```

## Option 3: Direct SQL Update (If Script Fails)

If the script has issues, you can update directly via SQL:

```sql
-- Enable sell_alert_enabled for all symbols with alert_enabled=True
UPDATE watchlist_items 
SET sell_alert_enabled = TRUE 
WHERE alert_enabled = TRUE 
  AND (sell_alert_enabled IS NULL OR sell_alert_enabled = FALSE);
```

## Expected Results

After running the script, you should see:
- ✅ List of symbols with sell alerts enabled
- ✅ Count of newly enabled symbols
- ✅ Summary of changes

## Next Steps

After enabling sell alerts:
1. Monitor backend logs for sell alert activity
2. Run diagnostic script to verify signal conditions
3. Check Telegram for sell alert messages
4. Verify monitoring dashboard shows sell alerts

## Troubleshooting

If you encounter errors:
1. Check database connection on AWS server
2. Verify database schema has `sell_alert_enabled` column
3. Check backend logs for any issues
4. Run diagnostic script: `python3 scripts/diagnose_sell_alerts.py`





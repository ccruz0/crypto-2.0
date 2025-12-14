# Deployment Guide - Fixes for Duplicate Alerts and Missing Orders

## Quick Start

### Option 1: Full Automated Deployment (Recommended)
```bash
cd ~/automated-trading-platform
bash sync_to_aws.sh
```

This will:
1. Build Docker images
2. Sync code to AWS
3. Deploy services
4. **Automatically apply database migration**

### Option 2: Manual Migration (If deployment fails)
```bash
cd ~/automated-trading-platform
bash apply_migration_aws.sh
```

### Option 3: Direct SQL Migration
```bash
ssh ubuntu@54.254.150.31
cd ~/automated-trading-platform
docker compose exec -T db psql -U trader -d atp -c "ALTER TABLE signal_throttle_states ADD COLUMN IF NOT EXISTS previous_price DOUBLE PRECISION NULL;"
```

## What Gets Fixed

### 1. Duplicate SELL Alerts ✅
- **Before:** Multiple alerts for same signal (e.g., 3 alerts for UNI_USDT at same price)
- **After:** Only one alert per signal, proper throttling with cooldown

### 2. Missing Sell Orders ✅
- **Before:** SELL alerts sent but no orders created
- **After:** Orders created automatically when `trade_enabled=YES` and `trade_amount_usd` configured

### 3. Missing Buy Signals After Toggle ✅
- **Before:** Toggling trade YES/NO/YES didn't trigger signals
- **After:** Auto-enables alerts and sets force flag for immediate triggering

## Verification Steps

After deployment, verify the fixes:

### 1. Check Migration Applied
```bash
ssh ubuntu@54.254.150.31
docker compose exec -T db psql -U trader -d atp -c "\d signal_throttle_states"
```
Should show `previous_price` column in the output.

### 2. Check Logs for Errors
```bash
bash scripts/aws_backend_logs.sh | grep -i "previous_price\|transaction.*aborted" | tail -20
```
Should show no errors (or only old errors before migration).

### 3. Test Toggle Behavior
1. Go to dashboard
2. Toggle a coin's Trade: NO → YES
3. Wait for signal (within 30 seconds)
4. Verify alert is sent
5. Verify order is created (if `trade_amount_usd` configured)

### 4. Test Duplicate Alert Prevention
1. Wait for a SELL signal
2. Verify only ONE alert is sent
3. Check that subsequent signals respect cooldown (5 minutes default)

## Rollback Plan

If issues occur:

### Rollback Code
```bash
git revert HEAD~5..HEAD
git push origin main
bash sync_to_aws.sh
```

### Rollback Migration (if needed)
```bash
ssh ubuntu@54.254.150.31
docker compose exec -T db psql -U trader -d atp -c "ALTER TABLE signal_throttle_states DROP COLUMN IF EXISTS previous_price;"
```

**Note:** Code handles missing column gracefully, so rollback is safe.

## Troubleshooting

### Migration Fails
- Check database connection: `docker compose exec db psql -U trader -d atp -c "SELECT 1;"`
- Check if column already exists: `docker compose exec db psql -U trader -d atp -c "\d signal_throttle_states"`
- Try direct SQL: See Option 3 above

### Orders Still Not Created
- Verify `trade_enabled=YES` in dashboard
- Verify `trade_amount_usd > 0` is configured
- Check logs: `bash scripts/aws_backend_logs.sh | grep -i "order.*created\|trade_enabled"`
- Verify `buy_alert_enabled=YES` (auto-enabled when trade is enabled)

### Alerts Still Duplicate
- Verify migration applied: Check for `previous_price` column
- Check throttle state: `bash scripts/aws_backend_logs.sh | grep -i "throttle.*state"`
- Restart signal monitor if needed

## Support

If issues persist:
1. Check `CODE_REVIEW_SUMMARY.md` for detailed technical information
2. Check `MIGRATION_INSTRUCTIONS.md` for migration details
3. Review logs: `bash scripts/aws_backend_logs.sh | tail -100`

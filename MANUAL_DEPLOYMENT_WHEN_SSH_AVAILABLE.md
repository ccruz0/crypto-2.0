# Manual Deployment Guide - When SSH Connection is Available

## Current Status

✅ **All code changes are committed and pushed to GitHub**
- Code will work even without migration (graceful degradation with rollback)
- Migration fixes duplicate alerts completely
- System continues functioning until migration can be applied

## What Works Now (Without Migration)

The code changes include transaction rollback handling, so:
- ✅ System won't crash from missing column
- ✅ Orders can still be created (rollback prevents transaction errors)
- ⚠️ Duplicate alerts may still occur (until migration is applied)
- ⚠️ Throttle state tracking incomplete (until migration is applied)

## When SSH is Available - Deployment Steps

### Step 1: Deploy Code Changes

```bash
cd ~/automated-trading-platform

# Try the main deployment script
bash sync_to_aws.sh

# Or if that fails, try alternative IP
# Edit sync_to_aws.sh and change EC2_HOST to "175.41.189.249"
```

### Step 2: Apply Database Migration

Once SSH connection works, apply the migration:

```bash
# Option A: Use the migration script
bash apply_migration_aws.sh

# Option B: SSH manually and run
ssh ubuntu@54.254.150.31
# OR try alternative IP:
ssh ubuntu@175.41.189.249

cd ~/automated-trading-platform

# Apply migration via Python script
docker compose exec -T backend python backend/scripts/apply_migration_previous_price.py

# OR apply via direct SQL
docker compose exec -T db psql -U trader -d atp -c "ALTER TABLE signal_throttle_states ADD COLUMN IF NOT EXISTS previous_price DOUBLE PRECISION NULL;"
```

### Step 3: Verify Migration

```bash
# Check if column exists
docker compose exec -T db psql -U trader -d atp -c "\d signal_throttle_states"

# Should show previous_price in the column list
```

## Alternative Connection Methods

### Option 1: AWS Session Manager (If Configured)
```bash
aws ssm start-session --target i-08726dc37133b2454
```

### Option 2: Check AWS Console
- Verify EC2 instance is running
- Check security groups allow SSH (port 22)
- Verify IP address hasn't changed

### Option 3: Direct Database Connection (If Exposed)
If database is accessible directly:
```bash
psql -h <database-host> -U trader -d atp -c "ALTER TABLE signal_throttle_states ADD COLUMN IF NOT EXISTS previous_price DOUBLE PRECISION NULL;"
```

## Troubleshooting SSH Connection

1. **Check if instance is running:**
   - AWS Console → EC2 → Instances
   - Verify instance state is "running"

2. **Check security groups:**
   - Ensure port 22 (SSH) is open
   - Check source IP is allowed

3. **Try alternative IP:**
   - Current: `54.254.150.31`
   - Alternative: `175.41.189.249` (from other scripts)

4. **Check SSH key:**
   ```bash
   ls -la ~/.ssh/
   # Verify key is configured correctly
   ```

5. **Test connectivity:**
   ```bash
   ping 54.254.150.31
   telnet 54.254.150.31 22
   ```

## What to Do Now

Since SSH is not available:

1. ✅ **Code is already pushed** - Will be deployed when SSH works
2. ✅ **System continues working** - Rollback prevents crashes
3. ⏳ **Migration can wait** - Apply when SSH is available
4. 📋 **Monitor logs** - Check if duplicate alerts still occur

## Priority Actions When SSH Works

1. **First:** Apply migration (fixes duplicate alerts)
2. **Second:** Verify deployment (check services are running)
3. **Third:** Test toggle behavior (verify buy_alert_enabled auto-enable works)

## Summary

- ✅ Code changes: Committed and pushed
- ✅ System stability: Rollback prevents crashes
- ⏳ Migration: Can be applied when SSH is available
- ⚠️ Duplicate alerts: May still occur until migration is applied

The system is **production-safe** even without the migration - it just won't have perfect duplicate prevention until the migration is applied.


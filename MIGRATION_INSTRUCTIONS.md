# Migration Instructions: Fix Duplicate SELL Alerts

## Problem
The `signal_throttle_states` table is missing the `previous_price` column, causing duplicate alerts and database errors.

## Solution
Apply the migration to add the missing column.

## How to Apply Migration

### Option 1: Using the Python Script (Recommended)

SSH into AWS and run:

```bash
ssh ubuntu@54.254.150.31
cd ~/automated-trading-platform
docker compose exec -T backend python backend/scripts/apply_migration_previous_price.py
```

### Option 2: Direct SQL Command

If the Python script doesn't work, use direct SQL:

```bash
ssh ubuntu@54.254.150.31
cd ~/automated-trading-platform
docker compose exec -T db psql -U trader -d atp -c "ALTER TABLE signal_throttle_states ADD COLUMN IF NOT EXISTS previous_price DOUBLE PRECISION NULL;"
```

### Option 3: Using the SQL Migration File

```bash
ssh ubuntu@54.254.150.31
cd ~/automated-trading-platform
docker compose exec -T db psql -U trader -d atp -f backend/migrations/add_previous_price_to_signal_throttle.sql
```

## Verification

After applying the migration, verify it worked:

```bash
docker compose exec -T db psql -U trader -d atp -c "\d signal_throttle_states"
```

You should see `previous_price` in the column list.

## What This Fixes

- ✅ Adds missing `previous_price` column
- ✅ Fixes duplicate SELL alerts
- ✅ Enables proper throttling/cooldown tracking
- ✅ Resolves database transaction errors

## Notes

- The migration is **idempotent** (safe to run multiple times)
- It checks if the column exists before adding it
- No data will be lost
- The system will continue working during migration


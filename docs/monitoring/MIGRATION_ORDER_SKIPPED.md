# Migration Guide: Add order_skipped Column

This guide provides step-by-step instructions to add the `order_skipped` column to the `telegram_messages` table.

## Migration Files

- **SQL Migration**: `backend/migrations/add_order_skipped_column.sql`
- **Python Migration**: `backend/scripts/migrate_add_order_skipped.py`

Both are idempotent (safe to run multiple times).

## Step 1: Run Migration Locally

From your Mac terminal:

```bash
cd /Users/carloscruz/automated-trading-platform && docker compose exec backend python scripts/migrate_add_order_skipped.py
```

**Expected output:**
```
INFO: Adding order_skipped column to telegram_messages table...
INFO: ✅ Added order_skipped column
INFO: ✅ Created index ix_telegram_messages_order_skipped
INFO: ✅ Verification: column=order_skipped, type=boolean, nullable=NO, default=false
INFO: ✅ Migration completed successfully!
```

**Verify locally:**
```bash
cd /Users/carloscruz/automated-trading-platform && docker compose exec db psql -U trader -d atp -c "SELECT column_name, data_type, is_nullable, column_default FROM information_schema.columns WHERE table_name = 'telegram_messages' AND column_name = 'order_skipped';"
```

**Check existing rows:**
```bash
cd /Users/carloscruz/automated-trading-platform && docker compose exec db psql -U trader -d atp -c "SELECT id, symbol, blocked, order_skipped, LEFT(message, 60) as msg FROM telegram_messages ORDER BY timestamp DESC LIMIT 5;"
```

All existing rows should have `order_skipped = false`.

## Step 2: Run Migration on AWS

SSH into AWS and run the migration:

```bash
ssh hilovivo-aws 'cd /home/ubuntu/automated-trading-platform && docker compose --profile aws exec backend-aws python scripts/migrate_add_order_skipped.py'
```

**Expected output:** Same as local.

**Verify on AWS:**
```bash
ssh hilovivo-aws 'cd /home/ubuntu/automated-trading-platform && docker compose --profile aws exec db-aws psql -U trader -d atp -c "SELECT column_name, data_type, is_nullable, column_default FROM information_schema.columns WHERE table_name = '\''telegram_messages'\'' AND column_name = '\''order_skipped'\'';"'
```

## Step 3: Restart Backend on AWS

Restart the backend service to pick up the new code:

```bash
ssh hilovivo-aws 'cd /home/ubuntu/automated-trading-platform && docker compose --profile aws restart backend-aws'
```

**Wait for container to be healthy:**
```bash
ssh hilovivo-aws 'cd /home/ubuntu/automated-trading-platform && docker compose --profile aws ps backend-aws'
```

Wait until status shows "Up" and health check passes.

## Step 4: Run Position Limit Test on AWS

Execute the test script:

```bash
ssh hilovivo-aws 'cd /home/ubuntu/automated-trading-platform && docker compose --profile aws exec backend-aws python scripts/test_position_limit_alert_behavior.py'
```

**Expected output:**
- Shows symbols with high exposure
- For symbols exceeding limit:
  - `order_skipped = True`
  - `blocked = False`
  - Message about "ORDEN NO EJECUTADA POR VALOR EN CARTERA"

## Step 5: Check Real Monitoring Rows on AWS

Query the last 5 rows to verify the behavior:

```bash
ssh hilovivo-aws 'cd /home/ubuntu/automated-trading-platform && docker compose --profile aws exec db-aws psql -U trader -d atp -c "SELECT id, symbol, blocked, order_skipped, LEFT(message, 80) as message FROM telegram_messages ORDER BY timestamp DESC LIMIT 5;"'
```

**For position-limit cases, you should see:**
- `blocked = false`
- `order_skipped = true`
- Message contains "ORDEN NO EJECUTADA POR VALOR EN CARTERA"

## Step 6: Frontend Sanity Check

1. Open the Monitoring UI in your browser
2. Navigate to the Telegram Messages section
3. Look for entries with position limit messages
4. Verify:
   - ✅ "ORDER SKIPPED" badge is shown (yellow/orange)
   - ❌ "BLOCKED" badge is NOT shown (red)

## Troubleshooting

### Migration Already Applied

If you see "Column order_skipped already exists", the migration was already run. This is safe - the script is idempotent.

### Column Not Found After Migration

If queries show the column doesn't exist:
1. Verify you're connected to the correct database
2. Check for transaction issues (ensure `conn.commit()` was called)
3. Re-run the migration script

### Backend Errors After Migration

If the backend fails to start:
1. Check logs: `docker compose --profile aws logs backend-aws`
2. Verify the model matches the database schema
3. Ensure all services are using the same database

## Rollback (if needed)

To remove the column (not recommended, but possible):

```sql
ALTER TABLE telegram_messages DROP COLUMN IF EXISTS order_skipped;
DROP INDEX IF EXISTS ix_telegram_messages_order_skipped;
```

**Note:** This will lose data. Only use if absolutely necessary.

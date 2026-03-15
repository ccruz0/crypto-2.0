# Telegram Update Deduplication Migration

## What the table is for

The `telegram_update_dedup` table prevents duplicate processing of Telegram updates. When multiple pollers or instances receive the same update (e.g. during deploy or race conditions), only the first to insert succeeds. Others detect the conflict and skip, avoiding duplicate replies and routing issues.

## How to run the migration on the EC2 server

1. SSH or SSM into the EC2 instance.
2. Navigate to the project:
   ```bash
   cd /home/ubuntu/automated-trading-platform
   ```
3. Run the migration (choose one):

   **Via Docker (recommended):**
   ```bash
   docker compose --profile aws exec -T db psql -U trader -d atp < backend/migrations/add_telegram_update_dedup.sql
   ```

   **Or with PGPASSWORD if needed:**
   ```bash
   PGPASSWORD='<your_db_password>' docker compose --profile aws exec -T db \
     psql -U trader -d atp -f - < backend/migrations/add_telegram_update_dedup.sql
   ```

   **Or pipe the file:**
   ```bash
   cat backend/migrations/add_telegram_update_dedup.sql | docker compose --profile aws exec -T db psql -U trader -d atp
   ```

## How to verify the table exists

```bash
PGPASSWORD='1234' docker compose --profile aws exec -T db \
  psql -U trader -d atp -c '\d telegram_update_dedup'
```

Expected output includes columns `update_id` (bigint, primary key) and `received_at` (timestamp).

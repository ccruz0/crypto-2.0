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
   docker compose --profile aws exec -T db sh -c 'PGPASSWORD=$POSTGRES_PASSWORD psql -U trader -d atp' < backend/migrations/add_telegram_update_dedup.sql
   ```
   The container has `POSTGRES_PASSWORD` in its env; `PGPASSWORD` tells psql to use it.

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

---

## Log verification

### Before fix (lock contention)

If both `backend-aws` and `backend-aws-canary` poll Telegram, you will see:

```
[TG] Another poller is active, cannot acquire lock
```

repeatedly in both containers. Commands in ATP Control will not reply.

### After fix (canary skips polling)

1. **Canary** (`backend-aws-canary`): Should not log lock attempts. With `RUN_TELEGRAM_POLLER=false` it returns early at `logger.debug` level (may not appear unless `--log-level debug`).

2. **Primary** (`backend-aws`): Should show:
   - `[TG] Poller lock acquired`
   - `[TG] process_telegram_commands called, LAST_UPDATE_ID=...`
   - `[TG][CMD] /start` (or whatever command you sent)
   - `[TG][REPLY] chat_id=... success=True`

### How to check logs on EC2

```bash
# SSH/SSM into EC2, then cd to repo (path may vary):
cd /home/ubuntu/automated-trading-platform || cd /home/ubuntu/crypto-2.0

# Primary backend (should acquire lock and process commands)
docker compose --profile aws logs backend-aws 2>&1 | grep -E '\[TG\]' | tail -50

# Canary (should not spam lock warnings)
docker compose --profile aws logs backend-aws-canary 2>&1 | grep -E '\[TG\]|Another poller' | tail -20
```

**Note:** If `cd` fails in SSM (e.g. "can't cd"), try running as ubuntu:
```bash
sudo -u ubuntu bash -c 'cd /home/ubuntu/automated-trading-platform && docker compose --profile aws logs backend-aws-canary 2>&1 | grep -E "TG|poller" | tail -15'
```

### ATP Control verification

After deploy, send in ATP Control:

- `/start` → should reply with menu
- `/help` → should reply
- `/runtime-check` → should reply with runtime info

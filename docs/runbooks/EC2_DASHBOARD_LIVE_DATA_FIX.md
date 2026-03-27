# EC2 Dashboard Live Data Fix (Post–Disk Full)

After freeing disk space and having healthy containers, use this runbook to restore dashboard visibility and live market data. It covers: **x-api-key** auth, **market-updater**, **market data**, **order_intents** table, and optional Telegram.

## 1. Auth: x-api-key (ATP_API_KEY)

The backend validates the `x-api-key` header against **ATP_API_KEY** (or **INTERNAL_API_KEY**). If unset, it falls back to `demo-key`.

- **Option A — Create env from scratch (no SSM / .env.aws):** run the helper script (generates ATP_API_KEY and writes `secrets/runtime.env`). **On EC2, pull first so the script exists:**

```bash
cd ~/crypto-2.0
git pull origin main
./scripts/aws/create_runtime_env.sh
```

If `.env` is missing, the script creates it from `.env.example` (or an empty file). Ensure `DATABASE_URL` and `POSTGRES_PASSWORD` are set (e.g. in `.env` or `.env.aws`) for the stack to start. Save the printed `ATP_API_KEY` for curl and the health/repair endpoint.

- **Option B — Set key manually:** create or edit `secrets/runtime.env` (never commit):

```bash
cd ~/crypto-2.0
python3 -c "import secrets; print(secrets.token_urlsafe(32))"   # copy output
# Add to secrets/runtime.env: ATP_API_KEY=<paste-the-generated-key-here>
```

Docker Compose loads `./secrets/runtime.env` for `backend-aws` and `market-updater-aws` via `env_file`.

## 2. Deploy and Restart

```bash
cd ~/crypto-2.0

git pull

# Restart so backend runs init_db (creates order_intents if missing) and loads ATP_API_KEY
docker compose --profile aws down
docker compose --profile aws up -d

# Wait for backend to be healthy (init_db runs on startup)
sleep 30
```

## 3. Fix order_intents Table (if health still shows order_intents_table_exists: false)

Either restart (above) so `init_db` runs, or call the repair endpoint once you have a valid API key:

```bash
cd ~/crypto-2.0

# Replace YOUR_ATP_API_KEY with the value from secrets/runtime.env
curl -s -X POST "http://127.0.0.1:8002/api/health/repair" \
  -H "x-api-key: YOUR_ATP_API_KEY" | jq
```

Expected:

```json
{ "ok": true, "message": "Repair completed (optional columns and order_intents table ensured)." }
```

## 4. Ensure Market-Updater Is Running

Market data freshness (and thus “market_updater” health) comes from the **market-updater-aws** container writing to the DB. If it was stopped, bring it up:

```bash
cd ~/crypto-2.0

docker compose --profile aws up -d market-updater-aws
docker compose --profile aws logs -f market-updater-aws --tail=50
```

Wait until you see periodic update logs (e.g. every 60s). No API key is required for the updater’s main job (it writes to the DB directly).

## 5. Validation (curl)

Run from the EC2 instance (replace `YOUR_ATP_API_KEY` with the key from `secrets/runtime.env`).

**Health system:**

```bash
curl -s http://127.0.0.1:8002/api/health/system | jq
```

Expect over time:

- `db_status`: `"up"`
- `market_data`: `fresh_symbols` > 0, `max_age_minutes` a number (after market-updater has run)
- `market_updater`: `is_running`: true, `last_heartbeat_age_minutes` set
- `trade_system`: `order_intents_table_exists`: true (after repair or restart)
- `global_status`: `"PASS"` or `"WARN"` (WARN acceptable if only market was stale initially)

**Engine run-once (protected):**

```bash
curl -s -X POST http://127.0.0.1:8002/api/engine/run-once \
  -H "x-api-key: YOUR_ATP_API_KEY" | jq
```

Expected: HTTP 200 and a JSON body with `"filled"` and `"rejected"` (no `"detail":"Invalid API key"`).

**Dashboard snapshot:**

```bash
curl -s http://127.0.0.1:8002/api/dashboard/snapshot | jq
```

(Optional) With API key if the snapshot endpoint is protected:

```bash
curl -s http://127.0.0.1:8002/api/dashboard/snapshot -H "x-api-key: YOUR_ATP_API_KEY" | jq
```

## 6. Telegram (Optional)

If you want Telegram enabled, set in `secrets/runtime.env` (or `.env.aws`):

- `RUN_TELEGRAM=true`
- `TELEGRAM_BOT_TOKEN_AWS` and `TELEGRAM_CHAT_ID_AWS` (or the env vars your backend reads)

Then restart backend (and market-updater if it sends alerts):

```bash
docker compose --profile aws up -d backend-aws market-updater-aws
```

If those vars are not set, health will show `telegram.enabled: false`; that is expected and acceptable.

## 7. Summary Checklist

| Step | Command / Action |
|------|-------------------|
| Set API key | Add `ATP_API_KEY=<secret>` to `secrets/runtime.env` |
| Generate key | `python3 -c "import secrets; print(secrets.token_urlsafe(32))"` |
| Deploy | `cd ~/crypto-2.0 && git pull` |
| Restart stack | `docker compose --profile aws down && docker compose --profile aws up -d` |
| Repair DB (if needed) | `curl -s -X POST http://127.0.0.1:8002/api/health/repair -H "x-api-key: $ATP_API_KEY" \| jq` |
| Start updater | `docker compose --profile aws up -d market-updater-aws` |
| Check health | `curl -s http://127.0.0.1:8002/api/health/system \| jq` |
| Check run-once | `curl -s -X POST http://127.0.0.1:8002/api/engine/run-once -H "x-api-key: $ATP_API_KEY" \| jq` |

**Definition of done:** `/api/health/system` shows `global_status` PASS (or WARN with market_data/market_updater passing once data is fresh), `order_intents_table_exists: true`, and `POST /api/engine/run-once` returns 200 with the chosen x-api-key.

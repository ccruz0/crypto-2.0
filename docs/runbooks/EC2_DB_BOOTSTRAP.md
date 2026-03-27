# EC2 DB Bootstrap (watchlist_items + market_data)

When **market_data** and **market_updater** stay FAIL with `relation "watchlist_items" does not exist`, the DB schema was never created. This runbook: pull, build backend, run schema bootstrap, then restart and validate. **Bootstrap DB schema before enabling the self-heal timer.**

**Rule:** `/api/health/fix` = restarts only (no schema mutation). Schema is created by `scripts/db/bootstrap.sh` (one-time or deploy-time) or by backend startup/repair.

**Health fallback:** If `watchlist_items` is empty, `/api/health/system` uses **market_prices** recency for `market_data` and `market_updater` (no need to seed watchlist for health to pass). Response includes `health_symbol_source`: `"watchlist_items"` or `"market_prices_fallback"`, and when using fallback a `message`: *"Watchlist empty; using market_prices fallback for health."* Empty watchlist is not fatal; PASS when ≥5 recent symbols in `market_prices`, WARN for 1–4, FAIL for 0.

---

## If git pull fails: "untracked working tree files would be overwritten"

EC2 may have local copies of `scripts/selfheal/*` that conflict with the repo. Use the repo version and pull:

```bash
cd /home/ubuntu/crypto-2.0
# Backup local selfheal if you need it, then replace with repo
rm -rf scripts/selfheal/heal.sh scripts/selfheal/run.sh scripts/selfheal/verify.sh \
  scripts/selfheal/systemd/atp-selfheal.service scripts/selfheal/systemd/atp-selfheal.timer
git pull origin main
```

Or move the whole directory aside and pull: `mv scripts/selfheal scripts/selfheal.bak && git pull origin main`

---

## Verify repo has the code (run first on EC2)

If these are missing, you're not deployed. Pull and push from your dev machine so EC2 gets the files.

```bash
cd /home/ubuntu/crypto-2.0
git log -1 --oneline
git status --porcelain
ls -la scripts/db/bootstrap.sh backend/app/database.py backend/app/api/routes_control.py
grep -RIn "ensure_optional_columns" backend/app | head -n 40
```

---

## Security: /api/health/fix must not be exposed

Unprotected schema creation would be a risk. We keep **fix** restarts-only; schema is in bootstrap/repair. Still ensure nginx does not expose `/api/health/fix` to the public internet (allow only localhost or internal).

Quick check from outside:

```bash
curl -sS -o /dev/null -w "%{http_code}\n" https://dashboard.hilovivo.com/api/health/fix
```

If you see 200, fix is reachable from the internet. Prefer 404/405/401. If exposed: restrict that route to 127.0.0.1 or require Basic Auth, or keep fix restarts-only (current behavior).

---

## One-shot block (copy/paste) — recommended order

1. Stop timer → 2. Pull → 3. .env/.env.aws → 4. **Build backend** (so new code is in image) → 5. Up + restart → 6. **Bootstrap** (after backend is updated) → 7. Fix + update-cache (90s) → 8. Validate → 9. Re-enable timer only if verify passes.

```bash
# 1) Stop timer
cd /home/ubuntu/crypto-2.0
sudo systemctl stop atp-selfheal.timer || true

# 2) Pull latest
git pull origin main

# 3) Ensure .env, .env.aws, .env.local, secrets/runtime.env (avoid compose errors)
[ ! -f .env ] && cp .env.example .env && echo "Created .env"
test -f .env.aws || cp .env .env.aws && echo "Created .env.aws from .env"
[ ! -f .env.local ] && touch .env.local && echo "Created empty .env.local"
mkdir -p secrets && [ ! -f secrets/runtime.env ] && touch secrets/runtime.env
ls -la .env .env.aws .env.local secrets/runtime.env

# 4) Rebuild backend to include schema fix (ensure_optional_columns creates watchlist_items etc.)
docker compose --profile aws build backend-aws
docker compose --profile aws up -d --remove-orphans
docker compose --profile aws restart
sleep 10

# 5) Bootstrap DB schema (watchlist_items + market tables)
chmod +x scripts/db/bootstrap.sh
./scripts/db/bootstrap.sh

# 6) Trigger fix (restarts only) + refresh cache
curl -sS -X POST --max-time 30 http://127.0.0.1:8002/api/health/fix | jq || true
curl -sS -X POST --max-time 90 http://127.0.0.1:8002/api/market/update-cache | jq || true

# 7) Validate
curl -s http://127.0.0.1:8002/api/health/system | jq
docker logs --tail 120 automated-trading-platform-market-updater-aws-1 2>&1 | tail -n 60
./scripts/selfheal/verify.sh; echo "exit=$?"

# 8) Re-enable timer only if verify passes
./scripts/selfheal/verify.sh && sudo systemctl start atp-selfheal.timer
sudo systemctl status atp-selfheal.timer --no-pager

# If you updated the timer unit (OnCalendar=*:0/2), reload and restart:
# sudo cp scripts/selfheal/systemd/atp-selfheal.timer /etc/systemd/system/ && sudo systemctl daemon-reload && sudo systemctl restart atp-selfheal.timer
```

---

## Diagnostics and stability

- **Market fallback check:** Run inside the backend container to see what fallback health would return (no prod data change):  
  `docker exec automated-trading-platform-backend-aws-1 python /app/scripts/diag/market_health_fallback_check.py`  
  Prints `distinct_recent_symbols`, `max_age_minutes`, `computed status` (PASS/WARN/FAIL).

- **verify.sh DEGRADED:** If `market_data` is WARN and `market_updater` is PASS, verify exits 0 with `DEGRADED:MARKET_DATA_WARN_UPDATER_PASS` and does not trigger heal.

- **ensure_env_aws:** Before compose, self-heal runs `scripts/aws/ensure_env_aws.sh` when present and executable; it creates `.env.aws` from `.env` or `.env.example` if missing.

- **Health snapshot (every 5 min):** Logs one JSON line per run to `/var/log/atp/health_snapshots.log` (ts, disk_pct, unhealthy_count, full `/api/health/system`). Install once:  
  `sudo cp scripts/selfheal/systemd/atp-health-snapshot.service scripts/selfheal/systemd/atp-health-snapshot.timer /etc/systemd/system/`  
  then `sudo systemctl daemon-reload` and `sudo systemctl enable --now atp-health-snapshot.timer`.

---

## Telegram alerts (optional)

Health snapshot failures can trigger a single Telegram message with cooldown. The script reads `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` from env files (no hardcoded secrets).

**Enable:**

1. Ensure `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` are set. Prefer **`secrets/runtime.env`** (loaded last so it overrides empty placeholders in `.env`/`.env.aws`). Alternatively use `TELEGRAM_BOT_TOKEN_AWS` / `TELEGRAM_CHAT_ID_AWS` in any of those files.
2. Install the timer:
   ```bash
   cd /home/ubuntu/crypto-2.0
   sudo cp scripts/selfheal/systemd/atp-health-alert.service scripts/selfheal/systemd/atp-health-alert.timer /etc/systemd/system/
   sudo systemctl daemon-reload
   sudo systemctl enable --now atp-health-alert.timer
   ```

**Optional env (defaults):** `ATP_HEALTH_SNAPSHOT_LOG` (/var/log/atp/health_snapshots.log), `ATP_ALERT_LINES` (5000), `ATP_ALERT_COOLDOWN_MINUTES` (30), `ATP_ALERT_RULE` (streak_fail_3). Supported rules: `streak_fail_3`, `fail_count_5_in_30m`, `updater_age_gt5_3runs`. State/cooldown: `/var/lib/atp/health_alert_state.json`.

**When you receive the alert:** See [ATP_HEALTH_ALERT_STREAK_FAIL.md](ATP_HEALTH_ALERT_STREAK_FAIL.md) for what each field means and quick diagnostics.

**Test:**

```bash
sudo systemctl start atp-health-alert.service
sudo journalctl -u atp-health-alert.service -n 50 --no-pager
```

Dry run (confirms env/decrypt and message formatting without sending):  
`ATP_ALERT_DRY_RUN=1 bash scripts/diag/health_snapshot_telegram_alert.sh`.  
With only `TELEGRAM_BOT_TOKEN_ENCRYPTED` (and key in `.telegram_key` or `secrets/telegram_key`), the script decrypts and should no longer print “missing”; use dry run to confirm.

---

## Optional: seed watchlist from market_prices

If you want `watchlist_items` populated from symbols already in `market_prices` (e.g. after a DB reset), run from the backend container:

```bash
docker exec automated-trading-platform-backend-aws-1 python /app/scripts/db/seed_watchlist_from_market_prices.py
```

Or from the repo root (with backend env): `python scripts/db/seed_watchlist_from_market_prices.py`. Inserts only missing symbols; safe to run multiple times. Health can still pass with an empty watchlist (market_prices fallback).

---

## Step-by-step (same order)

### 1) Stop the timer

```bash
cd /home/ubuntu/crypto-2.0
sudo systemctl stop atp-selfheal.timer || true
```

### 2) Pull latest

```bash
git pull origin main
```

### 3) .env, .env.aws, and secrets/runtime.env

```bash
[ ! -f .env ] && cp .env.example .env && echo "Created .env"
test -f .env.aws || cp .env .env.aws && echo "Created .env.aws from .env"
# Avoid "env file ... not found" from compose
mkdir -p secrets
[ ! -f secrets/runtime.env ] && ( touch secrets/runtime.env || cp secrets/runtime.env.example secrets/runtime.env 2>/dev/null || true )
[ ! -f .env.local ] && touch .env.local && echo "Created empty .env.local (compose may reference it)"
ls -la .env .env.aws .env.local secrets/runtime.env
```

Edit `.env` / `.env.aws` so `DATABASE_URL` and `POSTGRES_PASSWORD` are correct. Optionally add `ATP_API_KEY` to `secrets/runtime.env` for x-api-key endpoints.

### 4) Build backend and bring stack up

```bash
docker compose --profile aws build backend-aws
docker compose --profile aws up -d --remove-orphans
docker compose --profile aws restart
sleep 10
```

### 5) Bootstrap schema (after backend is updated)

```bash
chmod +x scripts/db/bootstrap.sh
./scripts/db/bootstrap.sh
```

Expected: `watchlist_items already exists.` or `watchlist_items created.` exit 0.

### 6) Fix (restarts only) + update-cache

```bash
curl -sS -X POST --max-time 30 http://127.0.0.1:8002/api/health/fix | jq || true
curl -sS -X POST --max-time 90 http://127.0.0.1:8002/api/market/update-cache | jq || true
```

### 7) Validate

```bash
curl -s http://127.0.0.1:8002/api/health/system | jq
docker exec postgres_hardened psql -U trader -d atp -c "\dt watchlist_items" || true
docker logs --tail 120 automated-trading-platform-market-updater-aws-1 2>&1 | tail -n 60
./scripts/selfheal/verify.sh; echo "exit=$?"
```

### 8) Re-enable timer only if verify passes

```bash
./scripts/selfheal/verify.sh && sudo systemctl start atp-selfheal.timer
sudo systemctl status atp-selfheal.timer --no-pager
```

---

## Deployment guard

Run **scripts/db/bootstrap.sh** once after bringing the stack up (e.g. in your deploy runbook or CI). That ensures `watchlist_items` (and related tables) exist before the timer or any service that depends on them runs.

---

## If bootstrap fails

- **Backend container not running:** `docker compose --profile aws up -d` (at least postgres + backend), then run `./scripts/db/bootstrap.sh` again.
- **Different container names:** `BACKEND_CONTAINER=your-backend ./scripts/db/bootstrap.sh`. Defaults: `postgres_hardened`, `automated-trading-platform-backend-aws-1`.
- **Still UndefinedTable:** Rebuild backend so it has the latest `database.py`: `docker compose --profile aws build backend-aws && docker compose --profile aws up -d backend-aws`, then run bootstrap again.

# EC2 DB Bootstrap (watchlist_items + market_data)

When **market_data** and **market_updater** stay FAIL with `relation "watchlist_items" does not exist`, the DB schema was never created. This runbook: pull, build backend, run schema bootstrap, then restart and validate. **Bootstrap DB schema before enabling the self-heal timer.**

**Rule:** `/api/health/fix` = restarts only (no schema mutation). Schema is created by `scripts/db/bootstrap.sh` (one-time or deploy-time) or by backend startup/repair.

---

## Verify repo has the code (run first on EC2)

If these are missing, you're not deployed. Pull and push from your dev machine so EC2 gets the files.

```bash
cd /home/ubuntu/automated-trading-platform
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
cd /home/ubuntu/automated-trading-platform
sudo systemctl stop atp-selfheal.timer || true

# 2) Pull latest
git pull origin main

# 3) Ensure .env and .env.aws exist (avoid compose errors)
[ ! -f .env ] && cp .env.example .env && echo "Created .env"
test -f .env.aws || cp .env .env.aws && echo "Created .env.aws from .env"
ls -la .env .env.aws

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
```

---

## Step-by-step (same order)

### 1) Stop the timer

```bash
cd /home/ubuntu/automated-trading-platform
sudo systemctl stop atp-selfheal.timer || true
```

### 2) Pull latest

```bash
git pull origin main
```

### 3) .env and .env.aws

```bash
[ ! -f .env ] && cp .env.example .env && echo "Created .env"
test -f .env.aws || cp .env .env.aws && echo "Created .env.aws from .env"
ls -la .env .env.aws
```

Edit `.env` / `.env.aws` so `DATABASE_URL` and `POSTGRES_PASSWORD` are correct.

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

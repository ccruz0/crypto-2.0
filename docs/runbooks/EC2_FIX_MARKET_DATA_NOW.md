# EC2 Fix: Market Data + Verify Script (Run Now)

**Goal:** Dashboard receives market data; `/api/health/system` shows market_data PASS + market_updater PASS. Restore verify.sh without fragile heredoc pastes. If the blocker is **missing `watchlist_items` table**, use [EC2_DB_BOOTSTRAP.md](EC2_DB_BOOTSTRAP.md) (run `scripts/db/bootstrap.sh` and ensure .env/.env.aws).

**Repo path on EC2:** `/home/ubuntu/automated-trading-platform`

---

## Checklist (order of actions)

1. Stop self-heal timer.
2. Restore `scripts/selfheal/verify.sh` from repo (git), validate syntax.
3. Ensure `.env` and `.env.aws` exist (copy from `.env.example` / `.env` if missing).
4. If `watchlist_items` is missing: run **scripts/db/bootstrap.sh** (see [EC2_DB_BOOTSTRAP.md](EC2_DB_BOOTSTRAP.md)).
5. Restart Docker and stack; call POST /api/health/fix and POST /api/market/update-cache.
6. Diagnose market-updater (container status, logs, env, connectivity).
7. Re-enable timer only when verify passes.

---

## Commands (copy/paste in order)

### 1) Stop timer and go to repo

```bash
sudo systemctl stop atp-selfheal.timer
cd /home/ubuntu/automated-trading-platform
```

### 2) Restore verify.sh (no heredoc paste — use git or emitter script)

**Option A — From git (preferred):**

```bash
cd /home/ubuntu/automated-trading-platform
git fetch origin main
git checkout origin/main -- scripts/selfheal/verify.sh
chmod +x scripts/selfheal/verify.sh
bash -n scripts/selfheal/verify.sh && echo "verify.sh syntax OK"
```

**Option B — Emitter script (corruption-proof, no paste):**  
If git doesn’t have the file or it’s still broken, pull so you have `scripts/selfheal/emit_verify_sh.py`, then run it to write a valid `verify.sh` from embedded base64:

```bash
cd /home/ubuntu/automated-trading-platform
git pull origin main
python3 scripts/selfheal/emit_verify_sh.py
bash -n scripts/selfheal/verify.sh && echo "verify.sh syntax OK"
```

Do not paste a long heredoc in the terminal; use git or the emitter.

### 3) Ensure .env and .env.aws exist

```bash
cd /home/ubuntu/automated-trading-platform
if [ ! -f .env ]; then cp .env.example .env; echo "Created .env"; fi
test -f .env.aws || cp .env .env.aws && echo "Created .env.aws from .env"
```

### 3b) If market_data/market_updater FAIL due to missing watchlist_items — bootstrap schema

```bash
cd /home/ubuntu/automated-trading-platform
chmod +x scripts/db/bootstrap.sh
./scripts/db/bootstrap.sh
```

See [EC2_DB_BOOTSTRAP.md](EC2_DB_BOOTSTRAP.md) for full steps.

Edit `.env` if you created it: set `DATABASE_URL` and `POSTGRES_PASSWORD` for the db service.

### 4) Restart Docker and stack

```bash
cd /home/ubuntu/automated-trading-platform
sudo systemctl restart docker
sleep 5
docker compose --profile aws up -d --remove-orphans
docker compose --profile aws restart
sleep 15
```

### 5) Trigger fix (restarts only) + refresh cache

```bash
curl -sS -X POST --max-time 30 http://127.0.0.1:8002/api/health/fix
curl -sS -X POST --max-time 90 http://127.0.0.1:8002/api/market/update-cache
```

### 6) Diagnose market-updater

```bash
docker ps -a --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}" | grep -E "market|NAMES"
docker logs --tail 200 automated-trading-platform-market-updater-aws-1 2>&1
```

Check: Is the container running (Up) or Exit/Restarting? Any errors (DB, import, connection)?

Inspect env and reachability from inside the container (optional):

```bash
docker exec automated-trading-platform-market-updater-aws-1 env | grep -E "DATABASE|API_BASE|RUNTIME" 2>/dev/null || true
docker exec automated-trading-platform-market-updater-aws-1 sh -c "curl -sS -o /dev/null -w '%{http_code}' --max-time 5 http://backend-aws:8002/api/health" 2>/dev/null || echo "curl failed"
```

### 7) If market-updater container is missing or exited: start it

```bash
cd /home/ubuntu/automated-trading-platform
docker compose --profile aws up -d market-updater-aws
sleep 30
docker logs --tail 100 automated-trading-platform-market-updater-aws-1 2>&1
```

### 8) Re-run health fix and update-cache once more (after updater has had time)

```bash
curl -sS -X POST --max-time 30 http://127.0.0.1:8002/api/health/fix
curl -sS -X POST --max-time 60 http://127.0.0.1:8002/api/market/update-cache
```

### 9) Validation

```bash
cd /home/ubuntu/automated-trading-platform
./scripts/selfheal/verify.sh; echo "exit=$?"
curl -s http://127.0.0.1:8002/api/health/system | jq
docker logs --tail 200 automated-trading-platform-market-updater-aws-1 2>&1
```

Expect: verify.sh prints PASS and exit=0; health/system shows market_data.status PASS, market_updater.status PASS; market-updater logs show periodic updates.

### 10) Re-enable timer only when verify passes

```bash
./scripts/selfheal/verify.sh && sudo systemctl start atp-selfheal.timer && echo "Timer started"
sudo systemctl status atp-selfheal.timer --no-pager
```

---

## If still failing

### market_data still FAIL (fresh_symbols 0)

- **Cause:** MarketData table empty or stale; market-updater not writing.
- **Check:** `docker logs --tail 300 automated-trading-platform-market-updater-aws-1` for errors (DB connection, watchlist empty, import errors).
- **Do:** Ensure `market-updater-aws` is running and has same `DATABASE_URL` as backend (from .env or env_file). Restart it: `docker compose --profile aws restart market-updater-aws`. Wait 1–2 minutes and call POST /api/market/update-cache again from the host (backend will run one update cycle).

### market_updater still FAIL (is_running false)

- **Cause:** Health infers “updater running” from market data freshness; if max_age is high or null, is_running is false.
- **Do:** If the container is Up and logging updates, wait for the next update cycle (e.g. 60s) and re-check /api/health/system. If the container keeps exiting, read the last 50 lines of logs and fix the reported error (env, DB, network).

### verify.sh still broken after git checkout

- **Cause:** Branch on EC2 doesn’t have the fixed file, or repo is detached.
- **Do:** Run the emitter (no paste): `cd /home/ubuntu/automated-trading-platform && python3 scripts/selfheal/emit_verify_sh.py` (after `git pull` so `emit_verify_sh.py` exists). Then `bash -n scripts/selfheal/verify.sh`. Alternatively copy `scripts/selfheal/verify.sh` from another machine via scp.

### Container name different

- **Do:** `docker compose --profile aws ps` and use the exact container name for logs, e.g. `docker logs --tail 200 <name>`.

---

## One-shot block (all steps, no timer start)

Run these in one go if you prefer (timer stays stopped until you start it after verify passes):

```bash
sudo systemctl stop atp-selfheal.timer
cd /home/ubuntu/automated-trading-platform
git pull origin main
python3 scripts/selfheal/emit_verify_sh.py || git checkout origin/main -- scripts/selfheal/verify.sh
chmod +x scripts/selfheal/verify.sh && bash -n scripts/selfheal/verify.sh && echo "verify.sh OK"
[ ! -f .env ] && cp .env.example .env && echo "Created .env"
sudo systemctl restart docker && sleep 5
docker compose --profile aws up -d --remove-orphans && docker compose --profile aws restart
sleep 15
curl -sS -X POST --max-time 30 http://127.0.0.1:8002/api/health/fix
curl -sS -X POST --max-time 60 http://127.0.0.1:8002/api/market/update-cache
docker compose --profile aws up -d market-updater-aws
sleep 30
curl -sS -X POST --max-time 30 http://127.0.0.1:8002/api/health/fix
curl -sS -X POST --max-time 60 http://127.0.0.1:8002/api/market/update-cache
./scripts/selfheal/verify.sh; echo "exit=$?"
curl -s http://127.0.0.1:8002/api/health/system | jq '.market_data, .market_updater'
# If above shows PASS: sudo systemctl start atp-selfheal.timer
```

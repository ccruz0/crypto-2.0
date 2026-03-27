# EC2 Self-Heal Deploy Runbook

Deploy and enable the production self-heal (timer + verify/heal scripts) on EC2 where the repo lives at `~/automated-trading-platform`. No backend code changes, no DB migrations, no secrets.

---

## Prerequisites

- SSH (or SSM) access to the EC2 instance.
- Repo at `/home/ubuntu/crypto-2.0` (or set `HOME` accordingly; systemd units assume `ubuntu` user and that path).

---

## 0) Bootstrap DB schema (before enabling timer) — deployment guard

**Rule:** `/api/health/fix` = restarts only (no schema mutation). Schema is created by `scripts/db/bootstrap.sh` (one-time or at deploy).

If `watchlist_items` (or other tables) are missing, market-updater crashes and health stays FAIL. Run **scripts/db/bootstrap.sh** once after bringing the stack up (e.g. in your deploy runbook or CI), **before** enabling the timer:

```bash
cd ~/automated-trading-platform
./scripts/db/bootstrap.sh
```

See [EC2_DB_BOOTSTRAP.md](EC2_DB_BOOTSTRAP.md) for full commands (including build backend → bootstrap → fix → validate). After bootstrap, run verify; only then enable the timer.

---

## 1) Get scripts and .env on the box

Scripts and `create_runtime_env.sh` live in the repo. If they are missing on EC2, pull (or fix repo path).

```bash
cd ~/automated-trading-platform
git pull origin main
```

If **scripts/selfheal/** is still missing, the repo on EC2 is behind or different. Ensure this commit (with `scripts/selfheal/` and `scripts/aws/create_runtime_env.sh`) is on the branch you deploy.

If **.env** is missing, create it; if **.env.aws** is missing, copy from .env so compose does not error on "env file .env.aws not found":

```bash
cd ~/automated-trading-platform
if [[ ! -f .env ]]; then
  cp .env.example .env
  echo "Created .env from .env.example. Edit .env and set DATABASE_URL and POSTGRES_PASSWORD."
fi
[[ ! -f .env.aws ]] && cp .env .env.aws && echo "Created .env.aws from .env."
```

Optional: use the helper to create `secrets/runtime.env` (and .env if missing):

```bash
./scripts/aws/create_runtime_env.sh
```

Then edit `.env` (and optionally `secrets/runtime.env`) with real values; do not commit them.

---

## 2) Make scripts executable

```bash
cd ~/automated-trading-platform
chmod +x scripts/selfheal/verify.sh scripts/selfheal/heal.sh scripts/selfheal/run.sh
```

---

## 3) Install systemd units (timer every 2 min)

```bash
cd ~/automated-trading-platform
sudo cp scripts/selfheal/systemd/atp-selfheal.service /etc/systemd/system/
sudo cp scripts/selfheal/systemd/atp-selfheal.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now atp-selfheal.timer
```

---

## 4) Check status and journal

```bash
sudo systemctl status atp-selfheal.timer --no-pager
sudo systemctl list-timers | grep -i atp-selfheal || true
sudo journalctl -u atp-selfheal.service -n 80 --no-pager
```

Expect: timer active; runs every ~2 min; logs show "PASS" or "HEALED", not repeated "STILL_FAIL".

---

## 5) Manual test

```bash
cd ~/automated-trading-platform
./scripts/selfheal/verify.sh; echo "exit=$?"
./scripts/selfheal/run.sh
```

Expect: `verify.sh` prints PASS and exit=0 when db, market_data, market_updater, and signal_monitor are PASS. If not, fix root cause (e.g. market-updater not running, no fresh data).

---

## If ExecStart fails (203/EXEC)

- **Cause:** Path in the service file does not exist (e.g. repo not at `/home/ubuntu/crypto-2.0` or scripts missing).
- **Fix:** Ensure repo is at `~/automated-trading-platform` and contains `scripts/selfheal/run.sh`. If you use another path, edit the service file:

```bash
sudo sed -i 's|/home/ubuntu/crypto-2.0|/your/actual/repo/path|g' /etc/systemd/system/atp-selfheal.service
sudo systemctl daemon-reload
sudo systemctl restart atp-selfheal.timer
```

---

## If .env is missing and compose fails

Heal script skips `docker compose` when `.env` is missing and prints a message. Create .env so the stack can start:

```bash
cd ~/automated-trading-platform
cp .env.example .env
# Edit .env: set DATABASE_URL and POSTGRES_PASSWORD (and any other required vars).
```

Then run heal manually or wait for the next timer run.

---

## Summary of self-heal actions (no code/DB/secrets)

- **verify.sh:** Disk &lt;90%, no unhealthy containers, API ok, db up, market_data PASS, market_updater PASS, signal_monitor PASS (telegram/trade_system ignored).
- **heal.sh:** Lock → if disk ≥90% truncate docker logs + prune → restart docker → restart stack (only if .env exists) → POST /api/health/fix → nginx reload only if `nginx -t` passes.

Exit codes from verify: 2=DISK, 3=CONTAINERS_UNHEALTHY, 4=API_HEALTH, 5=DB, 6=MARKET_DATA, 7=MARKET_UPDATER, 8=SIGNAL_MONITOR.

---

## Deploy checklist

- [ ] `cd ~/automated-trading-platform && git pull origin main`
- [ ] `scripts/selfheal/verify.sh`, `heal.sh`, `run.sh` exist and are executable
- [ ] `.env` exists (copy from `.env.example` if not); DATABASE_URL and POSTGRES_PASSWORD set
- [ ] systemd units copied to `/etc/systemd/system/`, `daemon-reload`, timer `enable --now`
- [ ] `systemctl status atp-selfheal.timer` shows active
- [ ] `./scripts/selfheal/verify.sh` returns PASS and exit 0 when stack is healthy
- [ ] `journalctl -u atp-selfheal.service -n 50` shows PASS or HEALED, not repeated STILL_FAIL

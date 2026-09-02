# ATP Primary Backend Health Watchdog

Synthetic probe of **primary** `GET /api/health` on loopback `:8002` with automatic restart of **only** `automated-trading-platform-backend-aws-1` when the event loop is blocked (e.g. `exchange_sync` / `candle_recorder`) while Docker still reports the container Up/healthy.

**Complements** (does not replace) the 5-minute health snapshot + Telegram streak alert (`scripts/diag/health_snapshot_telegram_alert.sh`) and Prometheus `InstanceDown`. Those paths can miss a hung-but-Up primary backend because nginx may still serve static 200 and canary `:8003` stays healthy.

---

## Problem context

| Symptom | Why existing alerts miss it |
|--------|-----------------------------|
| Primary container `Up (healthy)` | Docker healthcheck may pass while `/api/health` times out |
| Dashboard static assets load | nginx returns 200 for `/` without hitting blocked API |
| Canary `:8003` healthy | Watchdog must **never** restart canary |
| No `InstanceDown` Telegram | Host and container are technically up |

**Root cause (follow-up issue):** `exchange_sync` blocking the asyncio event loop on startup. Long-term fix: make health endpoint and sync non-blocking (separate issue — do not expand this PR).

**Prod hotfix (2026-09-02):** Installed on `i-087953603011543c5` at `/opt/atp/health_watchdog.sh` with `/etc/cron.d/atp-health-watchdog`. This repo path mirrors that behavior for review and future deploys.

---

## What it does

1. Every **2 minutes** (cron): `curl` `http://127.0.0.1:8002/api/health` with **5s** timeout.
2. Requires **2 consecutive** probe failures before action.
3. **Grace 10 min** after any restart — no restart logic during grace (probe may still run).
4. **Cooldown 15 min** between restart attempts.
5. **Max 2 restarts/hour** (rolling window).
6. Restarts **only** `automated-trading-platform-backend-aws-1` via `docker restart` (no `compose down`, no canary).
7. **Telegram** (ops channel, same env path as health snapshot / #630):
   - On successful restart: one alert with container name and timing params.
   - When max-restarts/hour reached and health still failing: one alert asking for manual intervention.

---

## Files

| Path | Role |
|------|------|
| `scripts/aws/health_watchdog.sh` | Watchdog logic |
| `scripts/aws/cron.d/atp-health-watchdog` | Cron template (`*/2 * * * *`) |
| `scripts/aws/install_health_watchdog.sh` | Install cron + seed state |

State: `/var/lib/atp/health_watchdog.state`  
Log: `/var/log/atp/health_watchdog.log`

---

## Install (EC2 prod)

```bash
cd ~/automated-trading-platform
git pull origin main   # after PR merge
sudo ./scripts/aws/install_health_watchdog.sh
```

**Seed grace** (avoid restart loop during an active sync storm — matches prod hotfix):

```bash
sudo ATP_HEALTH_WATCHDOG_SEED_GRACE=1 ./scripts/aws/install_health_watchdog.sh
```

Or manually:

```bash
sudo mkdir -p /var/lib/atp
echo "last_restart_epoch=$(date +%s)" | sudo tee /var/lib/atp/health_watchdog.state
# Full state format:
# consecutive_fails=0
# last_restart_epoch=<epoch>
# restart_epochs=
```

Verify cron:

```bash
cat /etc/cron.d/atp-health-watchdog
tail -f /var/log/atp/health_watchdog.log
```

---

## Parameters (environment)

| Variable | Default | Meaning |
|----------|---------|---------|
| `ATP_REPO_ROOT` | `/home/ubuntu/automated-trading-platform` | Repo path for Telegram env |
| `ATP_HEALTH_WATCHDOG_URL` | `http://127.0.0.1:8002/api/health` | Probe URL |
| `ATP_HEALTH_WATCHDOG_TIMEOUT_SEC` | `5` | curl connect + max time |
| `ATP_HEALTH_WATCHDOG_CONSECUTIVE_FAILS` | `2` | Failures before restart |
| `ATP_HEALTH_WATCHDOG_GRACE_SEC` | `600` | No restart for 10 min after restart |
| `ATP_HEALTH_WATCHDOG_COOLDOWN_SEC` | `900` | Min 15 min between restarts |
| `ATP_HEALTH_WATCHDOG_MAX_RESTARTS_HOUR` | `2` | Rolling hourly cap |
| `ATP_HEALTH_WATCHDOG_CONTAINER` | `automated-trading-platform-backend-aws-1` | **Fixed primary name**; script refuses canary/other |
| `ATP_HEALTH_WATCHDOG_STATE` | `/var/lib/atp/health_watchdog.state` | State file |
| `ATP_HEALTH_WATCHDOG_LOG` | `/var/log/atp/health_watchdog.log` | Log file |
| `ATP_HEALTH_WATCHDOG_DRY_RUN` | `0` | `1` = log only, no docker restart |
| `ATP_HEALTH_WATCHDOG_TELEGRAM` | `1` | `0` = skip Telegram |

Telegram credentials: loaded from `.env`, `.env.aws`, `secrets/runtime.env` (same as `scripts/diag/health_snapshot_telegram_alert.sh`); uses `TELEGRAM_CHAT_ID_OPS` when set; sends via `scripts/aws/_notify_telegram_fail.sh`.

---

## Manual test

```bash
# Dry run (no restart, Telegram logged if token present)
ATP_HEALTH_WATCHDOG_DRY_RUN=1 ./scripts/aws/health_watchdog.sh

# Simulate failure streak (point at dead port)
ATP_HEALTH_WATCHDOG_URL=http://127.0.0.1:59999/api/health \
  ATP_HEALTH_WATCHDOG_DRY_RUN=1 \
  ./scripts/aws/health_watchdog.sh
```

---

## Safety constraints

- **Never** restarts canary or any container whose name contains `canary`.
- **Never** runs `docker compose down` or rebuilds the stack.
- **Never** touches trading executor isolation or places orders.
- Only `docker restart automated-trading-platform-backend-aws-1` when all gates pass.

---

## Related runbooks

- [ATP_HEALTH_ALERT_STREAK_FAIL.md](ATP_HEALTH_ALERT_STREAK_FAIL.md) — 5m snapshot + remediation Telegram flow (#630 min-failure gate)
- [EC2_SELFHEAL_DEPLOY.md](EC2_SELFHEAL_DEPLOY.md) — verify/heal systemd timer (market data focus)
- [../agents/telegram-alerts/HEALTH_ALERT_FLOW.md](../agents/telegram-alerts/HEALTH_ALERT_FLOW.md) — health Telegram semantics

---

## Follow-up (separate issue)

Make `/api/health` and `exchange_sync` / `candle_recorder` non-blocking so a sync storm cannot stall the event loop while the container appears healthy. Until then, this watchdog limits outage duration with bounded auto-restart.

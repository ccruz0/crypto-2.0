# ATP Health Alert: streak_fail_3

## Purpose of these messages (action-required only)

You receive **only two kinds** of Telegram health messages:

1. **🚨 ATP Health — action required** — Sent **once per incident** when health is FAIL, automatic remediation has been tried and failed (max retries reached), and the issue is still unresolved. Includes root cause, time since failure, and clear action (runbook + optional “Run full fix now” button).
2. **✅ ATP Health recovered** — Sent **once** when the system transitions from FAIL to OK (after remediation, manual fix, or full fix).

**Suppressed (no Telegram):** first failure, each retry attempt, ongoing failure streak, “remediation starting”, “remediation finished still FAIL”, and “full fix running in background”. All of these are still **logged** to `/var/log/atp/health_alert_heal.log`.

See **[../agents/telegram-alerts/HEALTH_ALERT_FLOW.md](../agents/telegram-alerts/HEALTH_ALERT_FLOW.md)** for the full alert flow and example messages.

---

**When you see:** Telegram message "🚨 ATP Health — action required" with:

- **Root cause:** e.g. market data stale (market_updater not updating), or health check failing
- **Failing since:** X min ago
- **Action:** Runbook EC2_FIX_MARKET_DATA_NOW (or runbook for non-market incidents)

**Meaning:** The health snapshot saw 3+ consecutive FAILs. The script ran targeted remediation (restart market-updater, update-cache) up to 3 times; all attempts failed. You are notified once so you can take manual action.

When this alert is sent, a **Notion task** is created automatically (project: Infrastructure, type: monitoring). The backend must have `NOTION_API_KEY` and `NOTION_TASK_DB` set.

**Automatic resolution (order of operations):**
1. **Remediation first** (no Telegram): for `FAIL:MARKET_DATA:*` / `market_data`+`market_updater` FAIL, the script runs `remediate_market_data.sh` up to `ATP_HEALTH_REMEDIATION_MAX_ATTEMPTS` (default 3). Each run is logged only.
2. **Grace + verify:** After grace (default 300s), `verify.sh` runs again. If **PASS**, you get **one** “✅ recovered” Telegram and the incident is cleared.
3. If still **FAIL** after max attempts: **one** “action required” Telegram is sent **only if severity is critical** (e.g. market_data stale > 30 min, or API unreachable). Warning/info severity is logged only.
4. **Heavy heal** runs in background after max attempts (no separate Telegram); the single “action required” message includes severity and a button to trigger full fix if needed.

The **health snapshot** runs every 5 minutes; after recovery the log gets a fresh OK line and the FAIL streak clears.

---

## What each field means

| Field | Example | Meaning |
|-------|---------|--------|
| **verify_label** | `FAIL:API_HEALTH:missing` | `verify.sh` could not get `{"status":"ok"}` from `GET /api/health` (backend unreachable, timeout, or wrong response). |
| **market_data** | `FAIL` | No fresh market data (stale or no symbols). |
| **market_updater** | `FAIL` | Market updater not updating (container down or not writing heartbeats). |
| **market_updater_age_min** | `66.09` | Last market updater heartbeat was ~66 minutes ago. |
| **global_status** | `FAIL` | Overall system health is FAIL (derived from the components above). |

---

## Quick diagnostics (run on EC2 / where the snapshot runs)

### 1) Is the backend reachable?

```bash
curl -sS --max-time 5 http://127.0.0.1:8002/api/health
# Expect: {"status":"ok"} or similar with .status
curl -sS --max-time 5 http://127.0.0.1:8002/api/health/system | jq '.global_status, .market_data.status, .market_updater.status, .market_updater.last_heartbeat_age_minutes'
```

- If **connection refused / timeout**: backend container is down or not bound to 127.0.0.1:8002. Restart stack: `docker compose --profile aws up -d backend-aws` (from repo root).
- If **200 but** `global_status` / market_data / market_updater still FAIL: go to step 2.

### 2) Is market-updater running and updating?

```bash
docker ps -a --format "table {{.Names}}\t{{.Status}}" | grep -E "market|NAMES"
docker logs --tail 100 automated-trading-platform-market-updater-aws-1 2>&1
```

- If container is **Exited** or **Restarting**: see [EC2_FIX_MARKET_DATA_NOW.md](EC2_FIX_MARKET_DATA_NOW.md) (restart stack, start market-updater-aws, run update-cache).
- If container is **Up** but logs show errors (DB, import, network): fix those first; then re-run health fix and update-cache as in that runbook.

### 3) Where does the snapshot run?

The snapshot uses `BASE="${ATP_HEALTH_BASE:-http://127.0.0.1:8002}"`. If the script runs on a **different host** (e.g. another server), set `ATP_HEALTH_BASE` to the correct backend URL, or run the snapshot on the same host as the backend.

---

## Full fix (market_data + market_updater)

Follow **[EC2_FIX_MARKET_DATA_NOW.md](EC2_FIX_MARKET_DATA_NOW.md)**:

1. Stop self-heal timer.
2. Restore/validate `scripts/selfheal/verify.sh`.
3. Ensure `.env` / `.env.aws` and DB schema (e.g. run bootstrap if `watchlist_items` missing — see [EC2_DB_BOOTSTRAP.md](EC2_DB_BOOTSTRAP.md)).
4. Restart Docker and stack; POST `/api/health/fix` and `/api/market/update-cache`.
5. Ensure **market-updater-aws** is up and logging successful updates.
6. Re-run verify and health; re-enable timer only when `verify.sh` passes.

---

## Alert rule reference

- **streak_fail_3**: trigger when the last 3 snapshots in a row have `severity == "FAIL"`. Telegram “action required” is sent only when **remediation failed** (max attempts reached) **and** **severity == critical** (e.g. market_data stale > 30 min, or API unreachable), once per incident.
- **Severity:** `ATP_HEALTH_CRITICAL_UPDATER_AGE_MINUTES` (default 30). Market incident with `market_updater_age_minutes` > this → critical. Non-market API/backend down → critical. Otherwise warning (no Telegram).
- Snapshot log: `ATP_HEALTH_SNAPSHOT_LOG` (default `/var/log/atp/health_snapshots.log`).
- Remediation: `ATP_HEALTH_REMEDIATION_ENABLED` (default 1), `ATP_HEALTH_REMEDIATION_GRACE_SECONDS` (default **300**), `ATP_HEALTH_REMEDIATION_MAX_ATTEMPTS` (default 3). State file: `ATP_HEALTH_ALERT_STATE_FILE` (default `/var/lib/atp/health_alert_state.json`). State includes `first_fail_ts`, `action_alert_sent` for one-alert-per-incident.
- `remediate_market_data.sh`: skips `POST /api/health/fix` before `update-cache` by default (`ATP_REMEDIATE_SKIP_HEALTH_FIX=1`); `ATP_REMEDIATE_UPDATE_CACHE_TIMEOUT_SEC` default **300**; one retry after 30s if empty reply. Set `ATP_REMEDIATE_RUN_HEALTH_FIX=1` to run health/fix **after** update-cache.
- **Manual “Run full fix now” button:** The single “action required” message (market incidents) includes **▶ Run full fix now**. Tap it to write a trigger file; the next health check run will execute `full_fix_market_data.sh`. Trigger file: `ATP_TRIGGER_FULL_FIX_PATH` (default `$REPO_ROOT/logs/trigger_full_fix`). See [TELEGRAM_ATP_CONTROL_TRIGGER_FILE_FIX.md](TELEGRAM_ATP_CONTROL_TRIGGER_FILE_FIX.md) if you see "Permission denied".
- Health snapshot timer: every **5 minutes**. Heal-on-alert log: `/var/log/atp/health_alert_heal.log`.

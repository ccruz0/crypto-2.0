# ATP Health Alert: streak_fail_3

**When you see:** Telegram message "🔄 ATP Health Alert" with `Rule: streak_fail_3 (streak=3)` and snapshot lines like:

```
verify_label: FAIL:API_HEALTH:missing | market_data: FAIL | market_updater: FAIL
market_updater_age_min: 66.09 | global_status: FAIL
```

**Meaning:** The health snapshot script has seen **3 consecutive FAIL** results. The last snapshot shows which component(s) failed.

When this alert is sent to Telegram, a **Notion task** is created automatically (project: Infrastructure, type: monitoring) so you can track and resolve it. The task includes the snapshot summary and a link to this runbook. For the task to be created, the backend must have `NOTION_API_KEY` and `NOTION_TASK_DB` set in its environment.

**Automatic resolution (order of operations):**
1. **Remediation first** for `FAIL:MARKET_DATA:*` / `market_data`+`market_updater` FAIL: the alert script runs `scripts/selfheal/remediate_market_data.sh` (restart `market-updater-aws`, POST `/api/health/fix`, POST `/api/market/update-cache`) **before** sending the fail Telegram.
2. **Grace + verify:** After grace (`ATP_HEALTH_REMEDIATION_GRACE_SECONDS`, default **300s** so the first updater cycle can finish), `scripts/selfheal/verify.sh` runs again. If it **PASS**es, you get **one** Telegram recovery message and the incident is cleared (no spam).
3. If still **FAIL**, **one** escalation Telegram is sent; **repeated cycles are deduped** (no streak-growth bypass). Further escalations only after `ATP_HEALTH_ESCALATION_COOLDOWN_MINUTES` (default 120) when max remediation attempts are exhausted.
4. **Heavy heal** (`scripts/selfheal/heal.sh`, full stack) runs in background **only after** max remediation attempts, not on every alert.

The **health snapshot** runs every 5 minutes so after recovery the log gets a fresh OK line and the FAIL streak clears.

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

- **streak_fail_3**: alert when the last 3 snapshots in a row have `severity == "FAIL"`.
- Snapshot log: `ATP_HEALTH_SNAPSHOT_LOG` (default `/var/log/atp/health_snapshots.log`).
- Cooldown between Telegram alerts: `ATP_ALERT_COOLDOWN_MINUTES` (default 30).
- Remediation: `ATP_HEALTH_REMEDIATION_ENABLED` (default 1), `ATP_HEALTH_REMEDIATION_GRACE_SECONDS` (default **300**)
- `remediate_market_data.sh`: skips `POST /api/health/fix` before `update-cache` by default (`ATP_REMEDIATE_SKIP_HEALTH_FIX=1`) so the backend is not restarted while `update-cache` runs; `ATP_REMEDIATE_UPDATE_CACHE_TIMEOUT_SEC` default **300**; one retry after 30s if empty reply. Set `ATP_REMEDIATE_RUN_HEALTH_FIX=1` to run health/fix **after** update-cache., `ATP_HEALTH_REMEDIATION_MAX_ATTEMPTS` (default 3), `ATP_HEALTH_ESCALATION_COOLDOWN_MINUTES` (default 120). State file: `ATP_HEALTH_ALERT_STATE_FILE` (default `/var/lib/atp/health_alert_state.json`).
- **Telegram during remediation:** `ATP_HEALTH_REMEDIATION_TELEGRAM` (default 1) sends TG when remediation **starts** (what will run), when it **finishes still FAIL** (so you know to fix manually or wait), when **full heal** starts after max attempts, and when **recovered** (including after your manual fix). Set to `0` to disable those extra messages (escalation alert still sent per cooldown).
- Health snapshot timer: every **5 minutes** (so recovery is reflected in the log soon after self-heal). Heal-on-alert log: `/var/log/atp/health_alert_heal.log`.

# ATP Health Alert Flow (Telegram)

Alerting is **action-oriented**: you get Telegram only when human action is required or when the system has recovered. All other events are logged to `/var/log/atp/health_alert_heal.log`.

## New alert flow (summary)

| When | Telegram? | Log? |
|------|-----------|------|
| First FAIL (streak ≥ 3) | No | Yes |
| Remediation attempt 1, 2, 3 (start/finish) | No | Yes |
| Post-remediation still FAIL | No | Yes |
| Max remediation reached, still FAIL, **severity == critical** | **Yes — one “action required”** | Yes |
| Max remediation reached, still FAIL, severity warning/info | No (logged only) | Yes |
| Same incident, still FAIL (later runs) | No (no resend) | Yes |
| Full fix running in background | No | Yes |
| System transitions FAIL → OK | **Yes — one “recovered”** | Yes |

## Flow diagram (market_data / market_updater incident)

```
Snapshot every 5 min
       │
       ▼
┌──────────────────┐     OK      ┌─────────────────────┐
│ Last snapshot OK?│────────────►│ incident_open?     │──Yes──► Send ✅ recovered (once), clear state
└────────┬─────────┘             └─────────────────────┘
         │ No (FAIL)
         ▼
┌──────────────────┐
│ Streak ≥ 3?      │──No──► Exit (no Telegram, no remediation)
└────────┬─────────┘
         │ Yes
         ▼
┌──────────────────┐
│ New incident?    │ (fingerprint changed) → Reset attempts=0, first_fail_ts=now
└────────┬─────────┘
         │
         ▼
┌──────────────────┐     attempts < max     ┌─────────────────────────────────────┐
│ Market incident? │────────────────────────►│ Run remediate_market_data.sh (silent)│
└────────┬─────────┘     & script exists    │ Grace → verify.sh                   │
         │                                   │ PASS → Send ✅ recovered, clear state│
         │                                   │ FAIL → Persist attempts, exit (no TG)│
         │                                   └─────────────────────────────────────┘
         │
         ▼
┌──────────────────┐
│ action_alert_    │──Yes──► Exit (no resend; optionally run full_fix in background)
│ sent already?    │
└────────┬─────────┘
         │ No
         ▼
┌──────────────────┐     severity != critical
│ severity ==      │─────────────────────────────────────────────► Log only (no Telegram), exit
│ critical?        │
└────────┬─────────┘
         │ Yes
         ▼
┌──────────────────┐     remediation_failed AND critical
│ Send alert?      │─────────────────────────────────────────────► Send 🚨 action required (once)
└──────────────────┘     Persist action_alert_sent=true            Include Severity in message
                         Create Notion task                        Run full_fix in background (no TG)
```

## Severity classification

- **critical** — Send “action required” Telegram when remediation has failed and severity is critical:
  - Market incident and `market_updater_age_minutes` > `ATP_HEALTH_CRITICAL_UPDATER_AGE_MINUTES` (default **30**).
  - Non-market: backend/API unreachable (e.g. `verify_label` contains `API_HEALTH:missing` or `API_HEALTH:timeout`).
- **warning** — No Telegram: market data stale but age ≤ threshold, or other FAIL. Logged only.
- **info** — Minor/degraded; no Telegram.

Config: `ATP_HEALTH_CRITICAL_UPDATER_AGE_MINUTES` (default 30).

## State (one alert per incident)

- **incident_fingerprint:** `verify_label|market_data_status|market_updater_status`. Same fingerprint = same incident.
- **first_fail_ts:** When this incident was first opened. Used in the message as “Failing since: X min ago”.
- **action_alert_sent:** After sending the single “action required” message, set to `true` so we never resend for this incident until recovery.
- **remediation_attempts:** Count of remediation runs for this incident (capped by `ATP_HEALTH_REMEDIATION_MAX_ATTEMPTS`).

On **recovery** (last snapshot OK and incident_open), state is cleared: `incident_open=false`, `action_alert_sent=false`, `first_fail_ts=""`, `remediation_attempts=0`.

## Example messages

### 1. Action required (market_data / market_updater, severity critical)

```
🚨 ATP Health — action required (2026-03-17T14:00:00Z)
Severity: critical

Root cause: Market data stale (market_updater not updating). market_updater_age_min: 217 | verify_label: FAIL:MARKET_DATA:FAIL
Failing since: 45 min ago
Last snapshot: 2026-03-17T13:58:00Z | global_status: WARN

Action: Runbook EC2_FIX_MARKET_DATA_NOW — SSH to prod, restart stack + market-updater, POST /api/market/update-cache. Or tap the button below to trigger full fix on next health check.
Log: /var/log/atp/health_alert_heal.log

[▶ Run full fix now]
```

### 2. Action required (non-market, e.g. API health, severity critical)

```
🚨 ATP Health — action required (2026-03-17T14:00:00Z)
Severity: critical

Root cause: Health check failing. verify_label: FAIL:API_HEALTH:missing | market_data: n/a | market_updater: n/a
Failing since: 15 min ago
Last snapshot: 2026-03-17T13:58:00Z | global_status: FAIL

Action: Check backend and runbook ATP_HEALTH_ALERT_STREAK_FAIL.md. Log: /var/log/atp/health_alert_heal.log
```

When **severity is warning or info** (e.g. market_data stale ≤ 30 min), no Telegram is sent; the event is logged as `event=action_required_skipped severity=warning`.

### 3. Recovered (after remediation or manual fix)

```
✅ ATP Health recovered (2026-03-17T14:25:00Z)
Previous incident cleared. Last snapshot OK.
(If you applied a manual fix, this confirms it took effect.)
verify_label: PASS | market_data: PASS | market_updater: PASS
```

Or when recovery happened right after automated remediation:

```
✅ ATP Health recovered (2026-03-17T14:25:00Z)
Remediation succeeded after restart/update-cache.
verify_label: PASS (was FAIL:MARKET_DATA:FAIL)
```

## Compatibility

- **Health snapshot log:** Unchanged (`/var/log/atp/health_snapshots.log`, same JSONL format).
- **State file:** Same path (`ATP_HEALTH_ALERT_STATE_FILE`). New keys: `first_fail_ts`, `action_alert_sent`. Old state without these keys is treated as “action_alert_sent not set” (no resend until we send and set it).
- **Backend:** `POST /api/monitoring/health-alert` is still called when the single “action required” is sent (Notion task creation). Payload shape unchanged.
- **Telegram:** Same `send_tg` / `send_tg_with_button` and env (e.g. `TELEGRAM_CHAT_ID_OPS`, token resolution). No new env vars required.
- **Remediation and full fix:** `remediate_market_data.sh` and `full_fix_market_data.sh` / `heal.sh` behave the same; only Telegram sends were removed for intermediate steps.

## Files changed (reference)

| File | Change |
|------|--------|
| `scripts/diag/health_snapshot_telegram_alert.sh` | Silent remediation; one “action required” per incident (`action_alert_sent`); one “recovered”; message format with root cause + time since failure + action; **severity classification** (`classify_severity`); send only when **remediation_failed AND severity == critical**; include Severity in message and Notion payload; `ATP_HEALTH_CRITICAL_UPDATER_AGE_MINUTES` (default 30). |
| `backend/app/services/health_alert_incident.py` | State: `first_fail_ts`, `action_alert_sent`; suppress `send_fail_alert` when `action_alert_sent` for same incident. |
| `backend/app/api/routes_monitoring.py` | Health-alert endpoint accepts optional `severity` in payload; include in Notion task details. |
| `docs/runbooks/ATP_HEALTH_ALERT_STREAK_FAIL.md` | Updated purpose, order of operations, and alert rule reference; severity-based filtering. |
| `docs/agents/telegram-alerts/HEALTH_ALERT_FLOW.md` | This document; severity classification and example messages. |

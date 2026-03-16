# Root Cause Analysis: Repeated Telegram Scheduler Inactivity Alerts

## A. Current Behavior

### Code path from scheduler heartbeat check to Telegram message

1. **Scheduler loop** (`backend/app/services/agent_scheduler.py`)
   - `start_agent_scheduler_loop()` runs every `AGENT_SCHEDULER_INTERVAL_SECONDS` (default 300s / 5 min)
   - Each cycle: `run_agent_scheduler_cycle()` → retry → patch continuation → recovery → **anomaly detection** → sleep

2. **Anomaly detection** (`backend/app/services/agent_anomaly_detector.py`)
   - `run_anomaly_detection_cycle()` iterates `_DETECTOR_REGISTRY`
   - For `scheduler_inactivity`: calls `detect_scheduler_inactivity()`

3. **Scheduler inactivity detector** (`agent_anomaly_detector.py` lines 245–305)
   - Calls `get_recent_agent_events(limit=100)` from `agent_activity_log.py`
   - Data source: `logs/agent_activity.jsonl` (via `workspace_root()/logs/agent_activity.jsonl`)
   - Filters for `event_type` in `scheduler_cycle_started`, `scheduler_auto_executed`, `scheduler_approval_requested`
   - `last_cycle_at` = timestamp of most recent matching event (newest first)
   - `gap_minutes` = `(now - latest_ts).total_seconds() / 60`
   - If `gap > 15` min → returns anomaly dict with `last_cycle_at`, `gap_minutes`, `detected_at`

4. **Heartbeat source** (`agent_scheduler.py` line 134)
   - `run_agent_scheduler_cycle()` logs `scheduler_cycle_started` at the start of each cycle
   - Logged via `log_agent_event()` → `agent_activity_log.py` → appends to JSONL file

5. **Alert sending** (`agent_anomaly_detector.py` lines 384–388, before fix)
   - For each anomaly found: `_notify_telegram(...)` → `telegram_notifier.send_message(..., chat_destination="ops")`
   - **No deduplication, throttling, cooldown, or incident state**

### Files and functions involved

| File | Function |
|------|----------|
| `backend/app/services/agent_scheduler.py` | `start_agent_scheduler_loop`, `run_agent_scheduler_cycle`, `_log_event` |
| `backend/app/services/agent_activity_log.py` | `get_recent_agent_events`, `log_agent_event` |
| `backend/app/services/agent_anomaly_detector.py` | `run_anomaly_detection_cycle`, `detect_scheduler_inactivity`, `_notify_telegram` |
| `backend/app/services/telegram_notifier.py` | `send_message` |
| `backend/app/services/_paths.py` | `workspace_root` (log path resolution) |

---

## B. Root Cause

### Confirmed cause: **Missing alert suppression**

- Every anomaly detection cycle (every 5 min) that finds `scheduler_inactivity` calls `_notify_telegram()` unconditionally.
- There is no throttling, cooldown, or incident-open tracking for anomaly alerts.
- `telegram_notifier` duplicate detection applies only to trading signals (symbol/price/reason/side), not to anomaly messages.
- Result: **one Telegram message per cycle** while the incident is unresolved.

### Possible causes (underlying why `last_cycle_at` is stuck)

1. **Scheduler truly stopped** – `run_agent_scheduler_cycle` not running (e.g. NOTION_API_KEY/NOTION_TASK_DB unset → loop never starts).
2. **Stale activity log** – Log at `workspace_root()/logs/agent_activity.jsonl` is ephemeral in Docker; container restarts clear it. If the log is from an old run or a different path, `last_cycle_at` can stay old.
3. **Different process** – Anomaly detection only runs inside `agent_scheduler_loop`. If that loop is not started (no Notion keys), anomaly detection would not run. Repeated alerts imply the loop is running; if so, `scheduler_cycle_started` should be logged each cycle. A mismatch suggests either a path/volume issue or a failure before the log write.

---

## C. Evidence

### Code evidence

| Location | Evidence |
|---------|----------|
| `agent_anomaly_detector.py:384–388` (before fix) | `_notify_telegram(...)` called for every anomaly with no throttle check |
| `agent_anomaly_detector.py:358–391` | Loop structure: `if result is not None` → create task → notify (no suppression) |
| `telegram_notifier.py:163–184` | `_is_duplicate_message` uses symbol/price/reason/side; anomaly messages bypass this |
| `system_alerts.py:22–37` | `_should_send_alert` with 24h throttle exists for system alerts but **not** for anomaly detector |
| `agent_scheduler.py:437–524` | Scheduler loop runs anomaly detection every cycle |

### Log evidence

- No explicit logs for “throttled” or “suppressed” anomaly alerts before the fix.
- `anomaly_detection_cycle_done anomalies=1` every 5 min would indicate repeated detection and sending.

---

## D. What Should Happen Instead

1. **Initial alert** – Send Telegram when `scheduler_inactivity` is first detected.
2. **Cooldown** – Do not send again for the same anomaly type for N hours (e.g. 24h) while the incident is unresolved.
3. **Recovery** – When the anomaly clears (detector returns `None`), reset state so the next detection triggers a new alert.
4. **Notion tasks** – Can still be created each cycle (with existing dedup); Telegram is throttled separately.

---

## E. Minimal Fix Plan

1. Add per-anomaly-type throttling in `agent_anomaly_detector.py`.
2. Use `ANOMALY_ALERT_COOLDOWN_HOURS` (default 24) for the throttle window.
3. Before `_notify_telegram`, check `_should_send_anomaly_telegram(anomaly_type)`.
4. When a detector returns `None`, call `_clear_anomaly_incident(detector_name)` to reset for that type.
5. Do not change Notion task creation, recovery, or other alert paths.

---

## F. Cursor Patch (Applied)

### Changes in `backend/app/services/agent_anomaly_detector.py`

1. **Module-level state and helpers**
   - `_ANOMALY_ALERT_LAST_SENT: dict[str, datetime]`
   - `_get_anomaly_cooldown_hours()` – reads `ANOMALY_ALERT_COOLDOWN_HOURS` (default 24)
   - `_should_send_anomaly_telegram(anomaly_type)` – returns False if within cooldown
   - `_record_anomaly_alert_sent(anomaly_type)` – stores send time
   - `_clear_anomaly_incident(anomaly_type)` – clears state when anomaly resolves

2. **Loop changes**
   - When `result is None`: call `_clear_anomaly_incident(detector_name)` and `continue`.
   - When anomaly is found: only call `_notify_telegram` if `_should_send_anomaly_telegram(anomaly_type)`.
   - After sending: call `_record_anomaly_alert_sent(anomaly_type)`.

### Configuration

- `ANOMALY_ALERT_COOLDOWN_HOURS` (optional): 1–168, default 24.

---

## Summary

| Question | Answer |
|----------|--------|
| **Why is Telegram spamming?** | Anomaly detector sends a Telegram alert every 5 min for each unresolved anomaly, with no throttling. |
| **Is the scheduler actually dead or only appearing dead?** | Cannot be determined from code alone. `last_cycle_at` stuck at 2026-03-09 suggests either the scheduler is not running, the activity log is stale/wrong path, or a path/volume mismatch. |
| **What code change stops repeated alerts?** | Per-anomaly-type cooldown: send at most once per `ANOMALY_ALERT_COOLDOWN_HOURS` (default 24h) for the same anomaly type; reset when the detector returns `None`. |

# Scheduler Inactivity Alert — Fix (repeated alerts + heartbeat)

## Root cause

1. **Repeated alerts**  
   For `scheduler_inactivity`, alerts were throttled by a 24h cooldown (TradingSettings). If the DB write failed or the cooldown was not enforced correctly, or if the intent was “one alert per incident” (no resend until recovery), the system could still send multiple alerts for the same ongoing incident.

2. **Heartbeat visibility**  
   The detector only considered `scheduler_cycle_started`, `scheduler_auto_executed`, and `scheduler_approval_requested`. If the cycle ran but returned early (e.g. NOTION env missing) after logging `scheduler_cycle_started`, the heartbeat was present; if the loop wrote a heartbeat only after a full cycle, there was no separate “cycle completed” or “heartbeat updated” event, making it harder to confirm the loop was advancing.

3. **No recovery notification**  
   When the scheduler started running again (detector returned `None`), there was no “Scheduler recovered” Telegram, so operators had no clear signal that the incident was over.

## Files changed

| File | Change |
|------|--------|
| `backend/app/services/agent_scheduler.py` | Log `scheduler_loop_started` (activity log) when the loop starts. After each successful `run_agent_scheduler_cycle`, log `scheduler_cycle_completed` and `scheduler_heartbeat_updated`. On cycle exception, log `scheduler_cycle_failed` (reason: cycle raised). |
| `backend/app/services/agent_anomaly_detector.py` | Treat `scheduler_cycle_completed` and `scheduler_heartbeat_updated` as heartbeat events for inactivity detection. For `scheduler_inactivity` only: one alert per incident (send only if `last_sent` is None; no time-based resend). When detector returns `None` for `scheduler_inactivity` and we had previously sent, send one “Scheduler recovered” Telegram and log `scheduler_recovered`. Log `scheduler_inactivity_alert_suppressed` when we skip sending because we already sent for this incident. |

## Exact fix (summary)

- **Scheduler loop**  
  - On start: `_log_event("scheduler_loop_started", details={"interval_seconds": interval})`.  
  - After successful cycle: `_log_event("scheduler_cycle_completed", ...)` and `_log_event("scheduler_heartbeat_updated", details={})`.  
  - On cycle exception: `_log_event("scheduler_cycle_failed", details={"reason": "cycle raised", "error": str(e)})`.

- **Inactivity detector**  
  - Count as “last cycle” any of: `scheduler_cycle_started`, `scheduler_cycle_completed`, `scheduler_heartbeat_updated`, `scheduler_auto_executed`, `scheduler_approval_requested`.  
  - For `scheduler_inactivity` only: `_should_send_anomaly_telegram("scheduler_inactivity")` returns True only when `last_sent` is None (one alert per incident).  
  - When `detect_scheduler_inactivity()` returns `None`: if `last_sent` is set, send “Scheduler recovered” Telegram, log `scheduler_recovered`, then clear incident state.  
  - When we skip sending because we already sent: log `scheduler_inactivity_alert_suppressed`.

## Verification steps

1. **Backend running with scheduler**  
   - Ensure the backend starts the agent scheduler loop (e.g. `main.py` startup creates `start_agent_scheduler_loop()`).  
   - Check logs for: `agent_scheduler_loop_started`, `scheduler_loop_started` (activity log), and every ~5 min `scheduler_cycle_completed`, `scheduler_heartbeat_updated`.

2. **Activity log**  
   - Inspect `logs/agent_activity.jsonl` (under `workspace_root()`; set `ATP_WORKSPACE_ROOT` in Docker if needed).  
   - Confirm recent lines with `event_type` in `scheduler_cycle_started`, `scheduler_cycle_completed`, `scheduler_heartbeat_updated`.

3. **Simulate inactivity**  
   - Stop the scheduler (e.g. set `AGENT_AUTOMATION_ENABLED=false` and restart backend, or temporarily break the cycle so no heartbeat is written).  
   - Wait > 15 minutes. You should get **one** “Scheduler Inactivity” Telegram.  
   - Subsequent detection cycles (every ~5 min) should **not** send another Telegram; logs should show `scheduler_inactivity_alert_suppressed`.

4. **Recovery**  
   - Re-enable the scheduler / fix the cycle so heartbeats are written again.  
   - After the next anomaly run where `detect_scheduler_inactivity()` returns `None`, you should get **one** “Scheduler recovered” Telegram and see `scheduler_recovered` in the activity log.

## How to confirm the alert will stop

- **Same incident**  
  After the first “Scheduler Inactivity” alert, no further “Scheduler Inactivity” alerts are sent until the anomaly clears. Log lines: `scheduler_inactivity_alert_suppressed (already sent for this incident; will alert again when scheduler recovers)` and `scheduler_inactivity_alert_suppressed` in the activity log.

- **After recovery**  
  Once the scheduler is running again and the detector returns `None`, you get a single “Scheduler recovered” message; the next time the scheduler goes inactive, you get one new “Scheduler Inactivity” alert again (incident-based, not time-based).

- **Heartbeat**  
  If the loop is running, every cycle writes `scheduler_cycle_completed` and `scheduler_heartbeat_updated`, so `last_cycle_at` stays recent and the detector does not report inactivity.

# Telegram agent console

The Telegram agent console adds a small read-only view for authorized users to inspect recent agent state directly from chat.

Implementation: `backend/app/services/telegram_commands.py`, `backend/app/services/agent_activity_log.py`, and `backend/app/services/agent_telegram_approval.py`.

---

## Command

Use `/agent` to open the agent console menu.

The console shows a **scheduler health** block (from the agent activity log and approval state):

- **Last cycle** — Most recent scheduler run (any outcome).
- **Last auto-exec** — Last time the scheduler auto-executed a low-risk task.
- **Last approval request** — Last time the scheduler sent an approval request to Telegram.
- **Last failure** — Last time a scheduler cycle failed (e.g. prepare or send approval error).
- **Pending approvals** — Current count of approval requests awaiting a decision (from DB).

Then the menu shows these buttons:

- **Recent Activity**: shows the latest activity events from the structured agent activity log.
- **Pending Approvals**: shows approval requests that are still pending (from DB). Each item has a **View** button to open a detail view before approving or denying.
- **Last Failures**: shows recent `execution_failed`, `validation_failed`, and `execution_skipped` events.
- **Main Menu**: returns to the normal Telegram bot main menu.

Only authorized Telegram users should be able to access this command or its callbacks.

---

## Data sources

### Recent activity

Recent activity is read from the structured JSONL log exposed by `get_recent_agent_events()`.

- File location: `logs/agent_activity.jsonl`
- Source module: `backend/app/services/agent_activity_log.py`
- Typical fields shown in Telegram: `timestamp`, `event_type`, `task_title`

This is useful for a quick operator view without reading the raw log file.

### Pending approvals

Pending approvals are read from the **database** via `get_pending_approvals()` (table `agent_approval_states`). They survive process restart.

- Source module: `backend/app/services/agent_telegram_approval.py`
- List view: each row shows `task_id`, `task_title`, `requested_at` and a **View** button (`agent_detail:<task_id>`).
- Tapping **View** opens a **detail view** (task title, status, execution status, requested_at, project, type, priority, source, repo area, callback reason, approval summary). Buttons depend on status and execution state: **pending** → Approve, Deny, Back; **approved + not_started** → Execute Now, Back; **approved + failed** → Retry Execute, Back; **approved + running/completed** → Back only; **denied** → Back only. Execution state is stored in DB to prevent duplicate execution; retries are allowed after failure. See [Telegram approval flow](telegram-approval-flow.md#detail-view-inspect-before-approvedeny) and [Execute Now](telegram-approval-flow.md#execute-now-approved-tasks).

### Last failures

The failures view is derived from the activity log and filters for:

- `execution_failed`
- `validation_failed`
- `execution_skipped`

This gives a compact chat-friendly summary of recent blocked or failed runs.

---

## Persistence

- **Recent activity** and **Last failures** come from the JSONL file `logs/agent_activity.jsonl` and survive restart.
- **Pending approvals** come from the database (`agent_approval_states`) and survive restart; see [Telegram approval flow](telegram-approval-flow.md).

---

## Related

- [Human approval gate](human-approval-gate.md)
- [Telegram approval flow](telegram-approval-flow.md)
- [Agent activity log](agent-activity-log.md)

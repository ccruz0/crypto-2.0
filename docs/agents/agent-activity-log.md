# Agent activity log

The agent workflow records **major events** to a structured JSONL file so activity is visible without relying only on application logs.

Implementation: `backend/app/services/agent_activity_log.py`.

---

## Where logs are stored

- **Path:** `logs/agent_activity.jsonl` (relative to the repository root).
- The `logs/` directory is created automatically if it does not exist.
- The file is appended to; it is not rotated by this module (you can rotate or truncate it externally if needed).
- `logs/` is in `.gitignore`, so the activity log is not committed.

---

## Event structure

Each line in the file is a single JSON object with:

| Field        | Type   | Description |
|-------------|--------|-------------|
| `timestamp` | string | UTC ISO 8601 (e.g. `2026-03-07T12:41:22.123Z`). |
| `event_type`| string | Event kind (see below). |
| `task_id`   | string \| null | Notion task page ID when applicable. |
| `task_title`| string \| null | Task title when applicable. |
| `details`   | object | Extra context (varies by event). |

---

## Event types

| Event type           | When it is recorded |
|----------------------|----------------------|
| `task_prepared`      | A task was successfully claimed and prepared (planned → in-progress). |
| `approval_requested` | An approval request was sent to Telegram (with Approve/Deny buttons). |
| `approval_granted`   | An authorized user approved the task (e.g. via Telegram button). |
| `approval_denied`    | An authorized user denied the task (e.g. via Telegram button). |
| `execution_started`  | `execute_prepared_notion_task` began (apply step about to run). |
| `execution_completed`| Execution finished and the task was moved to **deployed**. |
| `execution_failed`   | Apply failed or deploy failed (task remains in-progress or testing). |
| `validation_failed`  | Validation step failed (task remains in testing). |
| `execution_skipped`  | Execution was not run because approval was required and not granted. |
| `version_proposed`   | A version proposal was created for a prepared task (includes proposed version, summary, affected files, validation plan). |
| `version_released`   | A released version was recorded after successful execution/deployment. |
| `strategy_analysis_generated` | Analysis-only strategy/signal proposal markdown was generated under `docs/analysis/`. |
| `strategy_analysis_validation_failed` | Strategy-analysis markdown validation failed (missing sections, links, or concrete proposal details). |
| `signal_performance_analysis_generated` | Historical signal-performance analysis markdown was generated under `docs/analysis/`. |
| `signal_performance_analysis_validation_failed` | Signal-performance analysis validation failed (missing sections, data source, confidence, links, or proposal details). |
| `profile_setting_analysis_generated` | Profile-setting analysis markdown was generated under `docs/analysis/`. |
| `profile_setting_analysis_validation_failed` | Profile-setting analysis validation failed (sections, targets, confidence, links, or proposal details). |
| `strategy_patch_generated` | Controlled allowlisted strategy patch was generated and patch note written under `docs/analysis/patches/`. |
| `strategy_patch_validation_failed` | Strategy patch validation failed (allowlist, note completeness, or localization checks). |

---

## How to read the file

- **From the repo root:** `logs/agent_activity.jsonl`.
- **One event per line:** each line is a full JSON object. Parse line by line (e.g. `json.loads(line)`).
- **Programmatic read:** use `get_recent_agent_events(limit=50)` from `agent_activity_log` to get the last N events (newest first).

Example (shell):

```bash
# Last 10 lines
tail -n 10 logs/agent_activity.jsonl

# Pretty-print last line
tail -n 1 logs/agent_activity.jsonl | python3 -m json.tool
```

Example (Python):

```python
from app.services.agent_activity_log import get_recent_agent_events

events = get_recent_agent_events(limit=20)
for e in events:
    print(e["timestamp"], e["event_type"], e.get("task_id"), e.get("details"))
```

---

## Example events

**Task prepared:**
```json
{
  "timestamp": "2026-03-07T12:41:22.123Z",
  "event_type": "task_prepared",
  "task_id": "abc12345-1234-5678-90ab-cdef12345678",
  "task_title": "Order synchronization failure",
  "details": {
    "repo_area": "Orders / Exchange Sync",
    "priority": "high"
  }
}
```

**Approval requested:**
```json
{
  "timestamp": "2026-03-07T12:42:00.456Z",
  "event_type": "approval_requested",
  "task_id": "abc12345-1234-5678-90ab-cdef12345678",
  "task_title": "Order synchronization failure",
  "details": {
    "chat_id": "-1001234567890",
    "sent": true,
    "message_id": 42
  }
}
```

**Execution completed:**
```json
{
  "timestamp": "2026-03-07T12:45:00.789Z",
  "event_type": "execution_completed",
  "task_id": "abc12345-1234-5678-90ab-cdef12345678",
  "task_title": "Order synchronization failure",
  "details": {
    "final_status": "deployed"
  }
}
```

---

## Why JSONL

- **One event per line** — Easy to append and to read with `tail` or line-based tools.
- **No external dependencies** — Plain JSON and the standard library; no database or message queue.
- **Structured** — Each record is a JSON object, so fields can be queried or aggregated by other tools.
- **Append-only** — Simple and safe: write failures inside `log_agent_event` are caught and never break the workflow.

---

## Related

- [Task execution flow](task-execution-flow.md)
- [Human approval gate](human-approval-gate.md)
- [Telegram approval flow](telegram-approval-flow.md)
- Backend: `agent_activity_log.log_agent_event`, `agent_activity_log.get_recent_agent_events`

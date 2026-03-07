# Agent scheduler

The agent scheduler runs a **single cycle** that prepares at most one task and either sends an approval request to Telegram or auto-executes low-risk tasks. It does not run continuously; it is intended to be invoked periodically (e.g. cron every 5 minutes).

Implementation: `backend/app/services/agent_scheduler.py`. CLI: `backend/scripts/run_agent_scheduler_cycle.py`.

---

## One task per cycle

- Each run of the scheduler processes **at most one** task.
- The cycle: **prepare** next planned task → if already in flight or completed, **skip** → if approval required, **send approval request** → if not required and auto-eligible, **auto-execute**.
- No batching, no parallel execution. This keeps behavior predictable and avoids overloading Notion/Telegram.

---

## Cycle flow

1. **Log** `scheduler_cycle_started`.
2. **Prepare** — `prepare_task_with_approval_check(project=..., type_filter=...)`. This fetches the next high-priority *planned* task from Notion, claims it (moves to in-progress), and attaches callback selection and approval decision.
3. **No task** — If no task is returned, log `scheduler_no_task` and return.
4. **In-flight check** — If this task is already in flight or completed (approval pending, or execution running/completed), log `scheduler_task_skipped` and return. This avoids duplicate approval requests and duplicate execution.
5. **Approval required** — If the approval gate says approval is required, call `send_task_approval_request(prepared_bundle)`, log `scheduler_approval_requested`, and return. A human approves or denies from Telegram.
6. **Auto-execute** — If approval is not required and `should_auto_execute(prepared_bundle)` is true, call `execute_prepared_task_if_approved(prepared_bundle, approved=True)`, log `scheduler_auto_executed`, and return.
7. **Otherwise** — Task is not auto-eligible (e.g. no safe callback or task targets blocked keywords). The scheduler appends a comment to the Notion task including a **scheduler cycle id** (e.g. `20260307-1805`) so you can cross-reference with `logs/agent_activity.jsonl`. Example: *"[2026-03-07T18:05:00Z] Scheduler cycle 20260307-1805 — Task prepared. Not auto-eligible for scheduler. Requires manual execution (approve from Telegram or run manually)."* Then log `scheduler_task_skipped` and return. This avoids leaving tasks stuck in-progress without explanation.
8. **On any failure** — Log `scheduler_cycle_failed` and return a structured failure result. The scheduler never raises.

---

## Approval-request path

When the approval gate marks the task as requiring human approval:

- The scheduler sends the approval request to Telegram (Approve / Deny / View Summary).
- The task is stored in `agent_approval_states` with status `pending`.
- No execution runs until a human approves from Telegram and (optionally) taps Execute Now.

---

## Low-risk auto-execution path

Auto-execution runs only when **all** of the following hold:

- **Approval not required** — `approval.required == False`.
- **Callback is documentation or monitoring triage** — `selection_reason` indicates documentation-like or monitoring/triage; i.e. the task was assigned the documentation or monitoring triage callback pack.
- **Task does not target blocked areas** — Task title, details, and inferred repo area do **not** contain: trading, trade, order, exchange, runtime, config, deploy, nginx, docker-compose, telegram_commands.

If any of these fail, the scheduler does **not** auto-execute; it either sends an approval request (if approval required) or skips (if not required but not auto-eligible).

---

## In-flight skip rules

A task is considered **already in flight or completed** and is skipped when:

- **Approval status is pending** — An approval request was already sent for this task; do not send another.
- **Execution status is running** — Execution has started; do not start again.
- **Execution status is completed** — Execution already finished; do not run again.

The scheduler uses `is_task_already_in_flight(task_id)` (backed by `agent_approval_states` and execution state) before sending an approval request or auto-executing.

---

## Activity log events

The scheduler logs these events to the agent activity log (JSONL):

| Event | When |
|-------|------|
| `scheduler_cycle_started` | Start of cycle (with optional project/type_filter in details). |
| `scheduler_no_task` | No planned task was available. |
| `scheduler_task_skipped` | Task was in flight/completed, or not auto-eligible. |
| `scheduler_approval_requested` | Approval request was sent to Telegram. |
| `scheduler_auto_executed` | Low-risk task was auto-executed. |
| `scheduler_cycle_failed` | Cycle failed (prepare, send approval, or execute threw). |

---

## Recommended cron usage

Run the scheduler **every 5 minutes** so that:

- New planned tasks are picked up within a few minutes.
- Approval requests are sent promptly.
- Low-risk tasks are executed without long delay.
- At most one task is processed per run, so overlap is avoided.

Example (run from repo root or backend, with env loaded):

```bash
# Every 5 minutes
*/5 * * * * cd /path/to/automated-trading-platform/backend && python scripts/run_agent_scheduler_cycle.py >> logs/scheduler.log 2>&1
```

Ensure `NOTION_API_KEY`, `NOTION_TASK_DB`, and (for approval path) `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` are set.

---

## CLI usage

From the backend directory:

```bash
python scripts/run_agent_scheduler_cycle.py
```

The script prints a JSON result (e.g. `{"ok": true, "action": "approval_requested", "task_id": "...", ...}`) and exits with 0 on success (including no task or skipped), 1 on failure.

---

## Related

- [Human approval gate](human-approval-gate.md) — When approval is required.
- [Telegram approval flow](telegram-approval-flow.md) — Approve/deny and Execute Now from Telegram.
- [Task preparation flow](task-preparation-flow.md) — How the next task is selected and claimed.
- [Agent activity log](agent-activity-log.md) — Where scheduler events are written.

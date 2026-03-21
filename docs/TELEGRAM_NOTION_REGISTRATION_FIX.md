# Telegram → Task System → Notion Registration Flow Fix

## Root Cause

The system had **two major gaps** where Telegram actions triggered work without creating Notion tasks:

1. **`/investigate` command** — Ran the agent directly via `handle_investigate_command` without ever calling `create_task_from_telegram_intent`. The agent executed and produced artifacts, but no task was registered in Notion.

2. **`/agent` command** — Same behavior: `handle_agent_command` ran the agent immediately without creating a Notion task first.

3. **`/task` command** — Already created Notion tasks correctly via `create_task_from_telegram_intent`. Low-impact filtering did **not** block creation (tasks get `status=backlog`, `priority=low`).

4. **Notion sync failures** — When `create_notion_task` returned `None` (API error, dedup, timeout), the task compiler stored to fallback and retried via scheduler. However:
   - Observability events were missing (`notion_sync_failed`, `notion_sync_started`, etc.)
   - Structured error logging was minimal

## Files Affected

| File | Change |
|------|--------|
| `backend/app/services/agent_telegram_commands.py` | Create Notion task before running agent; add `from_user` param; log `task_bypassed_without_registration` on failure |
| `backend/app/services/telegram_commands.py` | Pass `from_user` to `handle_investigate_command` and `handle_agent_command` |
| `backend/app/services/task_compiler.py` | Add observability: `telegram_task_received`, `task_creation_rejected`, `notion_sync_started`, `notion_sync_succeeded`, `notion_sync_failed`, `task_created`; add events in `retry_failed_notion_tasks` |
| `backend/app/services/notion_tasks.py` | Improve structured error log on API failure (`notion_sync_failed status=... title=...`) |

## Code Changes Summary

### 1. `agent_telegram_commands.py`

- **`handle_investigate_command`** and **`handle_agent_command`** now:
  1. Route/select agent first. If no match or agent not active: return (no execution, no task).
  2. When about to execute: call `create_task_from_telegram_intent(problem_text, telegram_user)` **before** running the agent.
  3. If `ok` or `fallback_stored`: proceed with agent execution.
  4. If neither: return error to user, log `task_bypassed_without_registration`, and **do not run** the agent.
- Added `_get_telegram_user(from_user)` helper.
- Added optional `from_user` parameter to both handlers.

### 2. `task_compiler.py`

- **`create_task_from_telegram_intent`**:
  - `telegram_task_received` — at entry
  - `task_creation_rejected` — when validation fails
  - `notion_sync_started` — before `create_notion_task`
  - `notion_sync_failed` — when `create_notion_task` returns `None`
  - `task_created` + `notion_sync_succeeded` — when task created or reused
- **`retry_failed_notion_tasks`**:
  - `notion_sync_started` — before each retry
  - `notion_sync_succeeded` — when fallback synced successfully
  - `notion_sync_failed` — when retry fails (exception or `None`)

### 3. `notion_tasks.py`

- `create_notion_task`: API error log now includes `title` for traceability.

## Validation Steps

### 1. Normal `/task` request via Telegram

```
/task Investigate why alerts are not sent
```

Expected: Task appears in Notion with status Planned or Backlog.

### 2. Vague/low-priority task

```
/task maybe try something later
```

Expected: Task still appears in Notion with status Backlog and priority Low.

### 3. `/investigate` action

```
/investigate repeated BTC alerts
```

Expected: Notion task created first, then agent runs. Task visible in Notion.

### 4. `/agent` action

```
/agent sentinel investigate repeated alerts
```

Expected: Notion task created first, then agent runs. Task visible in Notion.

### 5. Notion API failure simulation

- Set `NOTION_API_KEY` invalid or `NOTION_TASK_DB` invalid.
- Send `/task test task`.
- Expected: Task stored in fallback (`task_fallback.json`), user sees "Notion unavailable. Task stored locally and will be synced automatically."
- Restore correct env.
- Wait for scheduler cycle (or trigger `retry_failed_notion_tasks`).
- Expected: Task synced to Notion, removed from fallback.

### 6. Observability events

Check `logs/agent_activity.jsonl` for:

- `telegram_task_received`
- `task_created`
- `notion_sync_started`
- `notion_sync_succeeded`
- `notion_sync_failed`
- `task_creation_rejected`
- `task_bypassed_without_registration` (only when task creation fails and user cannot proceed)

## Proof That Telegram Tasks Now Appear in Notion

1. **`/task`** — Unchanged; already created tasks. Low-impact tasks still created with `status=backlog`.
2. **`/investigate`** — Now creates task before `route_task_with_reason` and agent execution. No agent run if task creation fails.
3. **`/agent`** — Same as `/investigate`. Task first, then agent.
4. **Fallback** — When Notion is down, tasks are stored in `task_fallback.json` and retried by `agent_scheduler` each cycle.
5. **Observability** — All events logged to `agent_activity.jsonl` for traceability.

## Important Rule

> **Telegram is the operational channel; Notion is the system of record. Telegram must never produce untracked work.**

All Telegram commands that imply work (`/task`, `/investigate`, `/agent`) now create or update a task record before any execution. If task creation fails (validation or Notion unavailable), the user receives an error and the agent does not run.

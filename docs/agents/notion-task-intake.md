# Notion Task Intake for OpenClaw

This document describes how agents (e.g. OpenClaw) should consume **pending tasks** read from the Notion "AI Task System" database and turn them into actionable development work.

**Intake + lifecycle:** The backend can read pending tasks via `notion_task_reader.py`. Agents can update task lifecycle status via `notion_tasks.py`. This doc focuses on **reading, prioritizing, planning, and safe status transitions** (not autonomous execution).

---

## Expected task data shape

`get_pending_notion_tasks()` and `get_high_priority_pending_tasks()` return a list of normalized task dicts. Each item has these keys (all strings; empty string if missing):

| Key | Description |
|-----|-------------|
| `id` | Notion page ID (for future status updates). |
| `task` | Short title (Notion "Task" property). |
| `project` | Project / area (e.g. "Infrastructure", "Backend"). |
| `type` | Kind of work: `monitoring`, `bug`, `improvement`, etc. |
| `status` | Current status (e.g. `planned`). |
| `priority` | `critical` \| `high` \| `medium` \| `low`. |
| `source` | Origin (e.g. "monitoring", "openclaw"). |
| `details` | Full description and context. |
| `github_link` | Optional URL to repo, file, or workflow. |

On any failure (missing env, network, API error), the functions return `[]` and log; they do not raise.

---

## Where tasks come from

- **Monitoring** creates Notion **incident** tasks when health checks fail (e.g. database down, trading engine unhealthy).
- **Trading bot** creates Notion **bug** tasks when order sync or order placement fails.
- Tasks are stored in the Notion database identified by `NOTION_TASK_DB`; the same DB is read by `get_pending_notion_tasks()` and `get_high_priority_pending_tasks()`.

---

## Fields agents should read first

When consuming a pending task (e.g. from `get_pending_notion_tasks()` or `get_high_priority_pending_tasks()`), use this order:

1. **task** — Short title of the work (e.g. "Database connectivity check failed", "Order placement system failure").
2. **priority** — `critical` | `high` | `medium` | `low`. Drives execution order (see below).
3. **project** — Area of the system (e.g. "Infrastructure", "Crypto Trading").
4. **type** — Kind of work: `monitoring`, `bug`, `improvement`, etc.
5. **details** — Full description and context; often includes component, error snippet, System Context block.
6. **github_link** — Optional URL to a repo, file, or workflow run.
7. **id** — Notion page ID (for future status updates).
8. **source** — Origin (e.g. "monitoring", "openclaw").

---

## How priority affects execution order

- **critical** — Address first (e.g. production-down, data integrity).
- **high** — Next (e.g. sync failures, API timeouts, Telegram/health failures).
- **medium** — Then (e.g. automation improvements, strategy tweaks).
- **low** — Last (e.g. non-urgent improvements).

Use `get_high_priority_pending_tasks()` to receive tasks already sorted by this order (critical → high → medium → low).

---

## Use /docs before touching code

Before implementing a task, the agent **must** use the repo’s documentation:

1. **[docs/architecture/system-map.md](../architecture/system-map.md)** — Components, APIs, data flow, dependencies.
2. **[docs/agents/context.md](context.md)** — Purpose of the project, critical modules, where docs and config live.
3. **[docs/agents/task-system.md](task-system.md)** — Task lifecycle (planned → in-progress → testing → deployed), how to plan and validate.
4. **[docs/decision-log/README.md](../decision-log/README.md)** — Past decisions; avoid re-proposing something already decided against.

**GitHub is the single source of truth** for code and technical docs. Notion is the project/task layer. Always prefer `/docs` and the main README over external or chat-only context.

---

## Safe execution recommendations

Before making changes for a task:

1. **Identify the affected module** — From `task`, `project`, and `details`, determine which part of the codebase is involved (e.g. `backend/app/services/exchange_sync.py`, `backend/app/api/routes_monitoring.py`).
2. **Check relevant runbooks** — See [docs/runbooks/](../runbooks/deploy.md), [docs/aws/RUNBOOK_INDEX.md](../aws/RUNBOOK_INDEX.md). For incidents: deploy, restart, dashboard health.
3. **Check decision-log** — Ensure the planned change does not conflict with recorded decisions.
4. **Avoid touching unrelated files** — Limit edits to the minimal set of files required for the task.
5. **Update docs if behavior or architecture changes** — If you change contracts, runbooks, or critical behavior, update the corresponding doc under `/docs` and link from [docs/README.md](../README.md) or the runbook index where appropriate.

---

## Updating task status in Notion (lifecycle)

Agents should update task status in Notion to reflect real work progress. Use:

- `update_notion_task_status(page_id, status, append_comment=None) -> bool`
- `advance_notion_task_status(page_id, current_status) -> bool`

**Allowed statuses:** `planned`, `in-progress`, `testing`, `deployed`.

### When to move to in-progress

Move **planned → in-progress** when:
- You are committing to take the task now (not just reading it).
- You have identified the likely affected area/module and are about to start a concrete plan.

Recommended: add a short `append_comment` describing what you’re doing next.

### When to move to testing

Move **in-progress → testing** when:
- Implementation work is complete and you are starting validation (tests/lint/manual checks/runbook verification).

### When to move to deployed

Move **testing → deployed** only when:
- Validations pass, and
- The change is merged and deployed to production (or deployed via the official runbook flow).

Reminder: **Do not set `deployed`** if deployment hasn’t happened yet or checks are incomplete.

---

## Intake flow (summary)

1. Read pending tasks via `get_pending_notion_tasks()` or `get_high_priority_pending_tasks()` (optional filters: `project`, `type_filter`).
2. For each task, read **task**, **priority**, **project**, **type**, **details**, **github_link**.
3. Consult **system-map**, **context**, **task-system**, **decision-log** before planning.
4. Choose the next task (usually highest priority) and set it to **in-progress** when you commit to working it.
5. Plan work (one objective per task; follow `docs/agents/task-system.md`).
6. Execute in a later step (code changes, tests, runbooks); advance status to **testing** and then **deployed** only after validations + deployment.

---

## Related

- [Agent context](context.md)
- [Task system](task-system.md)
- [System map](../architecture/system-map.md)
- Backend reader: `backend/app/services/notion_task_reader.py` (`get_pending_notion_tasks`, `get_high_priority_pending_tasks`)

## Task preparation flow (agents)

This document describes the **minimal, safe preparation flow** that agents (OpenClaw/Cursor) can run to turn Notion tasks into an actionable plan **without executing code changes yet**.

The flow is implemented in `backend/app/services/agent_task_executor.py`.

---

### Goal of this step

- **Read** pending tasks from Notion (Status = `planned`)
- **Prioritize** by `priority` (critical → high → medium → low)
- **Infer** the likely repo area (simple rules)
- **Build** a short execution plan
- **Claim** the task by moving it to `in-progress`
- **Append** the plan to the Notion task as a comment

This step **does not**:
- edit code
- run tests
- deploy

---

### How the next task is selected

The agent calls:

- `get_high_priority_pending_tasks(project=..., type_filter=...)`

Then selects the **first** task in the returned list (highest priority according to the ordering used by the reader).

If no tasks exist, preparation returns `None`.

---

### Repo area inference (rule-based)

The helper `infer_repo_area_for_task(task)` reads these fields:
- `task` (title)
- `project`
- `type`
- `details`

Then applies simple keyword/type rules to produce:
- `area_name`
- `likely_files`
- `relevant_docs`
- `relevant_runbooks`

Examples of rules:
- **Monitoring / Infrastructure** (keywords: `health`, `502`, `504`, `nginx`, `docker`, `deploy`, `ec2`, `db`) → `backend/app/api/routes_monitoring.py`, runbooks like `docs/runbooks/deploy.md`, `docs/runbooks/restart-services.md`
- **Orders / Exchange Sync** (keywords: `order sync`, `order history`, `open orders`) → `backend/app/services/exchange_sync.py`, order history runbooks under `docs/aws/`
- **Telegram / Notifications** (keywords: `telegram`, `bot`) → `backend/app/services/telegram_commands.py`
- **Trading Engine / Strategy** (keywords: `strategy`, `signal`, `throttle`) → `backend/app/services/signal_monitor.py`, `backend/app/services/signal_throttle.py`
- **Market Data** (keywords: `market-updater`, `ticker`, `price`, `websocket`) → `backend/app/api/routes_market.py`, market-data runbooks

The result is a hint, not a guarantee; the agent must still confirm by reading code + docs.

---

### Moving a task from planned → in-progress

Once the agent decides to take the top task, it claims it by calling:

- `update_notion_task_status(page_id, "in-progress")`

If claiming fails, the task should **not** be treated as owned by the agent; preparation returns a structured failure result.

---

### Plan generation

`build_task_execution_plan(task, repo_area)` outputs a short checklist such as:
- read required docs first (system-map, context, task-system, decision-log)
- read relevant runbooks for the inferred area
- inspect the likely affected files/modules
- confirm reproducibility (logs/endpoints/minimal repro)
- propose the smallest safe change and avoid unrelated edits
- update docs/runbooks if behavior changes
- validate before moving status to `testing`

The plan is appended to Notion as a comment after the task is successfully claimed.

---

### Minimal usage example (preparation only)

```python
from app.services.agent_task_executor import prepare_next_notion_task

prepared = prepare_next_notion_task(project=None, type_filter=None)
if prepared is None:
    print("No planned tasks.")
elif not prepared["claim"]["status_updated"]:
    print("Could not claim task:", prepared["claim"])
else:
    print("Claimed task:", prepared["task"]["task"])
    print("Area:", prepared["repo_area"]["area_name"])
    print("Plan:", prepared["execution_plan"])
```

---

### Read these docs before touching code

- `docs/architecture/system-map.md`
- `docs/agents/context.md`
- `docs/agents/task-system.md`
- `docs/decision-log/README.md`


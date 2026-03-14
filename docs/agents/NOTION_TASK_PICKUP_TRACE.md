# Notion Task Pickup — Flow and Filters

This document traces where the Notion task pickup is triggered and what filters determine which tasks get picked.

---

## 1. Status filter (main gate)

**File:** `backend/app/services/notion_task_reader.py`

The pickup queries tasks whose Status is one of:

| Internal | Notion display |
|----------|----------------|
| `planned` | Planned |
| `backlog` | Backlog |
| `ready-for-investigation` | Ready for Investigation |
| `blocked` | Blocked |

**Excluded:** `In Progress`, `Testing`, `Deployed`, `Done`, etc. (tasks already in the pipeline).

```python
# notion_task_reader.py
_INTERNAL_PICKABLE = ("planned", "backlog", "ready-for-investigation", "blocked")
_STATUS_VARIANTS = [
    notion_status_to_display(s) for s in _INTERNAL_PICKABLE
] + ["Planned", "Backlog", "Ready for Investigation", "Blocked"]
```

**Blocked tasks** are now included and will be picked when the scheduler runs.

---

## 2. Where pickup is triggered

| Trigger | Script / code | project | type_filter |
|--------|---------------|---------|-------------|
| Manual run | `./scripts/run_notion_task_pickup.sh` | `None` | `None` |
| CLI script | `backend/scripts/run_agent_scheduler_cycle.py` | `None` | `None` |
| Background loop | `agent_scheduler.start_agent_scheduler_loop()` | `None` | `None` |

**Conclusion:** No project or type filters are applied in normal runs. All tasks in Planned/Backlog/Ready for Investigation are eligible.

---

## 3. Call chain

```
run_notion_task_pickup.sh
  └─ run_agent_scheduler_cycle(project=None, type_filter=None)
       └─ prepare_task_with_approval_check(project=None, type_filter=None)
            └─ prepare_next_notion_task(project=None, type_filter=None)
                 └─ get_high_priority_pending_tasks(project=None, type_filter=None)
                      └─ get_pending_notion_tasks(project=None, type_filter=None)
                           └─ Notion API query: Status IN (Planned, Backlog, Ready for Investigation)
```

---

## 4. Optional filters (when passed)

If `project` or `type_filter` are passed (e.g. from an API or custom script):

- **project:** Case-insensitive substring match on the task’s Project field
- **type_filter:** Case-insensitive substring match on the task’s Type field

The standard pickup path does **not** pass these; they are only used by callers that explicitly set them (e.g. anomaly detector for creation, not pickup).

---

## 5. Other skip conditions (after a task is selected)

Even if a task passes the status filter, it can be skipped later:

| Condition | Location | Effect |
|-----------|----------|--------|
| `is_task_already_in_flight(task_id)` | `agent_scheduler.py` | Skips if task already has an approval record (prevents re-sending approval or re-processing) |
| `AGENT_AUTOMATION_ENABLED=false` | `agent_scheduler.py` | Background loop skips cycles entirely |
| Missing `NOTION_API_KEY` or `NOTION_TASK_DB` | `notion_task_reader.py` | Returns `[]`; no tasks fetched |

---

## 6. Scheduler loop (background)

**File:** `backend/app/services/agent_scheduler.py`

- Runs every `AGENT_SCHEDULER_INTERVAL_SECONDS` (default 300s / 5 min)
- Started via FastAPI startup when the backend runs
- Each cycle: `run_agent_scheduler_cycle()` → picks at most **one** task per cycle

---

## 7. Separate flows (different statuses)

| Flow | Statuses queried | Purpose |
|------|------------------|---------|
| Main intake | Planned, Backlog, Ready for Investigation | Pick new tasks for work |
| `continue_ready_for_patch_tasks` | ready-for-patch, Patching | Advance tasks through patch/validation |
| `retry_approved_failed_tasks` | (uses approval DB, not Notion status) | Retry tasks that were approved but failed |
| `run_recovery_cycle` | deploying, patching, etc. | Recovery for stuck tasks |

---

## 8. Quick checks when tasks aren’t picked

1. **Status:** Is the task **Planned**, **Backlog**, **Ready for Investigation**, or **Blocked**?
2. **Config:** Are `NOTION_API_KEY` and `NOTION_TASK_DB` set (e.g. in `secrets/runtime.env` or `backend/.env`)?
3. **Automation:** Is `AGENT_AUTOMATION_ENABLED` true? (Default is true.)
4. **Already in flight:** Does the task already have an approval record? (Check agent activity log / approval DB.)
5. **Backend running:** Is the backend (and its scheduler loop) running? For manual runs, use `./scripts/run_notion_task_pickup.sh`.

---

## Related

- [notion-task-intake.md](notion-task-intake.md) — How agents consume pending tasks
- [agent-scheduler.md](agent-scheduler.md) — Scheduler behavior
- [NOTION_TASK_TO_CURSOR_AND_DEPLOY.md](../runbooks/NOTION_TASK_TO_CURSOR_AND_DEPLOY.md) — Full flow from Notion to deploy

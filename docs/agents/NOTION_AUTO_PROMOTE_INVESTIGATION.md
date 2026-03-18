# Auto-promote new Investigation tasks (Planned → Ready for Investigation)

## Problem

Tasks created with **Type = Investigation** and **Status = Planned** (e.g. by a user like Carlos) are not picked up by the scheduler, which only queries for **Ready for Investigation**, **Planned**, **Backlog**, and **Blocked**. If the user leaves Status as **Planned**, the task is technically pickable but in practice the scheduler prioritizes **Ready for Investigation**. Manually changing Status to "Ready for Investigation" was required.

## Fix

New Investigation tasks with **Status = Planned** and **Source** in an allowed list (default: **Carlos**) are automatically updated to **Ready for Investigation** once per scheduler cycle, so they are picked up without manual change.

## Files changed

| File | Change |
|------|--------|
| `backend/app/services/notion_tasks.py` | Added `promote_planned_investigation_tasks_to_ready()`, `_get_auto_promote_source_names()`, and `DEFAULT_AUTO_PROMOTE_SOURCES`. |
| `backend/app/services/agent_scheduler.py` | At start of `run_agent_scheduler_cycle()`, call `promote_planned_investigation_tasks_to_ready()` once (non-fatal on failure). |

## Logic path

1. **Scheduler cycle start**  
   `agent_scheduler.run_agent_scheduler_cycle()` runs (every `AGENT_SCHEDULER_INTERVAL_SECONDS`, default 300s).

2. **After Notion preflight**  
   If Notion env is present, the scheduler calls  
   `notion_tasks.promote_planned_investigation_tasks_to_ready()` **once** per cycle.

3. **Promotion function**  
   - Reads allowed sources from env `NOTION_AUTO_PROMOTE_SOURCES` (comma-separated) or default `("Carlos",)`.
   - Fetches tasks with Status = **Planned** via `notion_task_reader.get_tasks_by_status(["Planned", "planned"], max_results=50)`.
   - Filters in Python: **Type** (normalized) must be `"investigation"`, **Source** (case-insensitive) must be in the allowed list.
   - For each matching task: calls `update_notion_task_status(task_id, "ready-for-investigation")`.
   - Logs each promotion: `auto_promoted_to_ready_for_investigation task_id=<id>`.
   - Returns list of promoted task IDs.

4. **No loops**  
   Promotion runs once per cycle; it does not re-scan in a loop.

5. **No override of in-progress**  
   Only tasks with Status = **Planned** are queried; tasks already **Investigating**, **Patching**, etc. are never touched.

6. **New tasks only**  
   Only **Planned** + **Investigation** + allowed **Source** are updated; after update they become **Ready for Investigation** and will not match again.

## Configuration

- **NOTION_AUTO_PROMOTE_SOURCES** (optional): Comma-separated list of Source values. Tasks whose Source (case-insensitive) matches one of these are promoted. Default: `Carlos`.  
  Example: `NOTION_AUTO_PROMOTE_SOURCES=Carlos,User`

## Verification steps

1. **Create a test task in Notion**  
   - Type = **Investigation**  
   - Status = **Planned**  
   - Source = **Carlos** (or another value in `NOTION_AUTO_PROMOTE_SOURCES`)

2. **Run one scheduler cycle** (or wait for the next interval):  
   - Via API: trigger the agent scheduler endpoint that runs one cycle.  
   - Or wait `AGENT_SCHEDULER_INTERVAL_SECONDS` (default 300s) for the background loop.

3. **Check logs**  
   - Look for: `auto_promoted_to_ready_for_investigation task_id=<your-task-id>`.  
   - Optionally: `agent_scheduler: auto_promoted_planned_investigation count=1 task_ids=[...]`.

4. **Check Notion**  
   - The task’s Status should now be **Ready for Investigation**.

5. **Confirm no double promotion**  
   - On the next cycle, the same task should not be promoted again (it is no longer Planned).

6. **Optional: disable**  
   - Set `NOTION_AUTO_PROMOTE_SOURCES=` (empty) to disable auto-promotion; no tasks will match the allowed source list.

# Notion "Planned" Task Pickup — Root Cause and Fix

## 1. Code path that selects Notion tasks

| Step | Module | Function | Purpose |
|------|--------|----------|---------|
| 1 | `agent_scheduler.py` | `start_agent_scheduler_loop()` | Runs every `AGENT_SCHEDULER_INTERVAL_SECONDS` (default 300) |
| 2 | `agent_scheduler.py` | `run_agent_scheduler_cycle()` | One cycle: prepare task → approval or auto-execute |
| 3 | `agent_task_executor.py` | `prepare_task_with_approval_check()` | Calls `prepare_next_notion_task()` or `prepare_task_by_id()` |
| 4 | `agent_task_executor.py` | `prepare_next_notion_task()` | Fetches tasks via `get_high_priority_pending_tasks()` |
| 5 | `notion_task_reader.py` | `get_high_priority_pending_tasks()` | Calls `get_pending_notion_tasks()`, sorts by priority |
| 6 | `notion_task_reader.py` | `get_pending_notion_tasks()` | **Queries Notion API** with Status filter |

## 2. Exact eligible statuses

**Internal (backend):** `planned`, `backlog`, `ready-for-investigation`, `blocked`

**Display (queried from Notion):** `Planned`, `Backlog`, `Ready for Investigation`, `Blocked`

**Comparison logic:** Notion API filter uses `equals` — **exact match, case-sensitive**. If Notion stores `"planned"` (lowercase), a query for `"Planned"` returns 0 results.

## 3. Root cause: invalid query values

The code was sending **lowercase variants** (`planned`, `backlog`, etc.) to the Notion filter. Notion Select/Status options require **exact option names** (e.g. `Planned`, `Backlog`). Lowercase values cause:

```
400 validation_error: "select option 'planned' not found for property 'Status'"
```

## 4. Fix applied

**File:** `backend/app/services/notion_task_reader.py`

1. **Use only exact valid Notion option names** (`NOTION_PICKABLE_STATUS_OPTIONS`):
   - `Planned`, `Backlog`, `Ready for Investigation`, `Blocked`
   - No lowercase variants — they cause 400.

2. **Constants:**
   - `NOTION_PICKABLE_STATUS_OPTIONS` — exact values sent to Notion API
   - `INTERNAL_PICKABLE_STATUSES` — normalized internal form (after parse)

3. **Normalization** happens in `_parse_page` via `_normalize_status_from_notion` (after fetch).

4. **Debug logging:**
   - `notion_pickup_status_variants` — logs internal pickable statuses and all variants queried
   - `notion_pickup_debug first_page_status_raw` — logs raw Status value from first result
   - `notion_pickup_task_rejected` — logs when a task is rejected (project_mismatch, type_mismatch)
   - `get_high_priority_pending_tasks` — logs when no tasks found

3. **Diagnostic:** `get_raw_status_distribution()` — queries Notion with no filter and returns distribution of raw Status values (to verify exact casing).

## 5. Other conditions that can block pickup

| Condition | Where | Effect |
|-----------|-------|--------|
| **Project filter** | `prepare_task_with_approval_check(project="X")` | Only tasks whose Project contains "X" |
| **Type filter** | `prepare_task_with_approval_check(type_filter="Y")` | Only tasks whose Type contains "Y" |
| **Already in flight** | `is_task_already_in_flight()` | Skips if task has approval record |
| **Scheduler interval** | `AGENT_SCHEDULER_INTERVAL_SECONDS` | Default 300s; task checked at most every 5 min |
| **Automation disabled** | `AGENT_AUTOMATION_ENABLED=false` | Scheduler skips cycles |
| **Missing config** | `NOTION_API_KEY`, `NOTION_TASK_DB` | Returns empty list |

## 6. Files changed

- `backend/app/services/notion_task_reader.py` — `NOTION_PICKABLE_STATUS_OPTIONS`, `INTERNAL_PICKABLE_STATUSES`, removed lowercase variants, debug logging
- `backend/scripts/diagnose_stuck_notion_tasks.py` — pickable check uses exact option names
- `backend/tests/test_agent_scheduler_notion.py` — `test_only_sends_valid_notion_status_options`, updated mocks
- `docs/agents/NOTION_PLANNED_PICKUP_FIX.md` — this document

## 7. How to manually trigger a task

### Option A: Run one scheduler cycle (recommended)

```bash
# On EC2 (backend-aws running):
./scripts/run_notion_task_pickup.sh

# Or via SSM:
./scripts/run_notion_task_pickup_via_ssm.sh

# For a specific task:
TASK_ID=<notion-page-id> ./scripts/run_notion_task_pickup.sh
```

### Option B: Run diagnostic first

```bash
cd backend && python scripts/diagnose_stuck_notion_tasks.py
```

Output includes:
- Raw Status values in Notion (exact casing)
- Pickable tasks count
- Stale tasks

### Option C: Wait for scheduler

The scheduler runs every 5 minutes (configurable via `AGENT_SCHEDULER_INTERVAL_SECONDS`). Ensure `AGENT_AUTOMATION_ENABLED` is not `false`.

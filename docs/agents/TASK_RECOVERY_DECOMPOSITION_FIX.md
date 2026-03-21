# ATP / OpenClaw Task Recovery and Decomposition Fix

## Root Cause Analysis

The previous flow looped because:

1. **Unbounded retries**: Stuck tasks were retried indefinitely (up to MAX_RETRIES=3) with no strategy change. Each retry moved the task back to `ready-for-investigation`, but the same monolithic task often failed again for the same reasons.

2. **No decomposition path**: Complex multi-phase tasks (e.g. "verify full flow", "root cause and fix") were treated like simple bugs. The system never split them into smaller, tractable subtasks.

3. **Generic Needs Revision fallback**: When transitions failed or metadata was missing, some paths could fall back to `needs-revision` without explicit `revision_reason` / `verify_summary` / etc., leaving tasks in a non-actionable state.

4. **Alert spam**: Repeated "task appears stuck" and "already being investigated" messages without any state or strategy change.

5. **Notion write failures**: Status updates could fail when the Notion Status property was the native Kanban type (required `{"status": {"name": "..."}}`, not `select` or `rich_text`). This was fixed separately.

## Lifecycle Table: Before vs After

| Scenario | Before | After |
|----------|--------|-------|
| Stuck investigation (1st time) | → ready-for-investigation | → ready-for-investigation, alert with "Retry 1/2" |
| Stuck investigation (2nd time) | → ready-for-investigation | → ready-for-investigation, alert with "Retry 2/2" |
| Stuck investigation (3rd time) | → ready-for-investigation (repeat forever) | → decompose into 2–5 children OR block |
| Complex task at retry limit | → block | → decompose into subtasks, parent → waiting-on-subtasks |
| Decomposition fails | N/A | → block with "Decomposition not applicable or failed" |
| All children complete | N/A | Parent → ready-for-investigation for aggregation |
| Needs revision | Sometimes without metadata | Never without revision_reason/verify_summary/missing_inputs/decision_required |
| Blocked | After MAX_RETRIES | After MAX_AUTO_REINVESTIGATE (2) with decompose attempt |
| Alert spam | Every 30 min same message | Cooldown + strategy-change detection; retry count in message |

## Files Changed

| File | Changes |
|------|---------|
| `backend/app/services/task_decomposition.py` | **NEW**: Complexity detection, decomposition logic, child creation |
| `backend/app/services/task_health_monitor.py` | MAX_AUTO_REINVESTIGATE=2; decomposition path; parent aggregation; improved alerts |
| `backend/app/services/notion_tasks.py` | Added `waiting-on-subtasks`, `split-into-subtasks` statuses |
| `backend/app/services/agent_scheduler.py` | Call `check_parent_aggregation()` each cycle |
| `backend/tests/test_task_decomposition.py` | **NEW**: Tests for decomposition, retry limits |
| `backend/tests/test_task_health_monitor.py` | Updated `_send_stuck_alert` test for `retry_attempt` |
| `docs/agents/notion-ai-task-system-schema.md` | Added `waiting-on-subtasks` to Status values |

## Example: Decomposition

**Parent task:**
- Title: "Verify full automated patch -> verify -> deploy flow"
- Status: investigating (stuck after 2 retries)

**Generated children (4):**
1. Verify patch entry point and validation logic
2. Verify post-patch validation and tests
3. Verify deploy trigger conditions
4. Verify final result reconciliation

Each child:
- Has `[ATP_SUBTASK]` block in Details with `parent_task_id`, `subtask_index`, `subtask_total`, `subtask_scope`
- Created with Status `ready-for-investigation`
- Parent moves to `waiting-on-subtasks`

When all children reach a terminal status (done, blocked, investigation-complete, etc.), parent moves to `ready-for-investigation` for final aggregation.

## Test Results

```
50 passed in 0.35s
```

- `test_task_decomposition.py`: 11 tests
- `test_task_health_monitor.py`: 12 tests (including updated cooldown test)
- `test_task_status_transition.py`: 10 tests
- `test_telegram_approval_callback.py`: 17 tests

## Notion Setup Required

Add the Status option **"Waiting on Subtasks"** to your AI Task System database if using Select/Status type. If Status is Rich text, no change needed.

## Go / No-Go Recommendation

**GO** – The implementation is minimal, preserves existing invariants (needs-revision metadata, patch/deploy approval), and adds decomposition as a recovery path. Parent aggregation is in-memory; after process restart, decomposed parents will need manual requeue or a future persistence layer. This is acceptable for MVP.

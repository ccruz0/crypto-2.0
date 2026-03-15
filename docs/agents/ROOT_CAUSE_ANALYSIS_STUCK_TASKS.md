# Root Cause Analysis: Stuck Tasks in AI Task System

**Date:** 2026-03-15  
**Scope:** OpenClaw + Notion task orchestration — why tasks remain in Blocked, In Progress, Planned, etc.

---

## 1. Executive Summary

Tasks get stuck because:

1. **Stale "In Progress" / "Investigating" tasks are never recovered** — The main intake only fetches `planned`, `backlog`, `ready-for-investigation`, `blocked`. Tasks moved to `in-progress` or `investigating` (claimed) are excluded from future fetches. If the worker crashes or agent dies before execution, those tasks remain stuck indefinitely. **No recovery playbook exists for these statuses.**

2. **Blocked tasks have no retry/terminal logic** — Blocked tasks are picked every cycle and moved to `in-progress`. There is no distinction between temporary vs permanent blocks, no retry backoff, and no explicit terminal handling.

3. **`get_tasks_by_status` early-break bug** — The function stops after the first status that returns any tasks, so tasks in later statuses (e.g. `patching` when `ready-for-patch` is queried first) may never be fetched.

4. **Missing instrumentation** — Logging does not clearly show why a task was skipped, retried, blocked, or completed. Status transition failures can be silent.

---

## 2. Actual Task Lifecycle Found in Code

```
[Intake] get_pending_notion_tasks() / get_high_priority_pending_tasks()
         → Filters: planned, backlog, ready-for-investigation, blocked ONLY
         → File: notion_task_reader.py:213-410

[Prepare] prepare_next_notion_task() → prepare_task_with_approval_check()
         → Selects top task, infers repo area, builds plan
         → Claims by: update_notion_task_status(page_id, "in-progress")
         → File: agent_task_executor.py:396-458

[Execute] execute_prepared_task_if_approved() → execute_prepared_notion_task()
         → apply → testing → validate → deploy → done/deployed
         → On crash: task stays in-progress (no finally-block reset)
         → File: agent_task_executor.py:596-1000

[Continuation] continue_ready_for_patch_tasks()
         → get_tasks_by_status(["ready-for-patch", "patching"])
         → advance_ready_for_patch_task()
         → File: agent_scheduler.py:342-385

[Recovery] run_recovery_cycle()
         → orphan_smoke (deploying, >10 min)
         → revalidate_patching (patching, >15 min)
         → missing_artifact (investigation-complete, ready-for-patch, patching)
         → File: agent_recovery.py
         → NO playbook for: in-progress, investigating
```

**Critical gap:** Tasks in `in-progress` or `investigating` are never re-fetched by intake and never recovered by any playbook.

---

## 3. Expected Lifecycle from Documentation

From `docs/agents/task-system.md` and `docs/agents/task-execution-flow.md`:

- **Legacy:** planned → in-progress → testing → deployed
- **Extended:** backlog → ready-for-investigation → investigating → investigation-complete → ready-for-patch → patching → testing → awaiting-deploy-approval → deploying → done

Documentation expects:
- Stale tasks to be recoverable
- Blocked tasks to have explicit handling
- Status transitions to be consistent

---

## 4. Discrepancies Between Docs and Code

| Aspect | Documentation | Code |
|--------|---------------|------|
| Stale in-progress | Implied recoverable | No recovery; never re-picked |
| Stale investigating | Implied recoverable | No recovery; never re-picked |
| Blocked retry | Not specified | Picked every cycle; no backoff |
| Status filters | Intake = pickable | Correct: planned, backlog, ready-for-investigation, blocked |
| Recovery playbooks | deploying, patching | deploying, patching, missing_artifact; NOT in-progress/investigating |

---

## 5. Root Cause(s) of Stalled Tasks

### 5.1 Stale "In Progress" / "Investigating" (Primary)

- **Location:** `notion_task_reader.py` line 254: `_INTERNAL_PICKABLE = ("planned", "backlog", "ready-for-investigation", "blocked")`
- **Effect:** Tasks in `in-progress` or `investigating` are never returned by `get_pending_notion_tasks`.
- **Flow:** Task claimed → moved to in-progress → worker crashes → task never re-picked.
- **Recovery:** `agent_recovery.py` has no playbook for these statuses.

### 5.2 Blocked Tasks

- **Location:** Blocked is in `_INTERNAL_PICKABLE`; picked every cycle.
- **Effect:** Blocked tasks are claimed and moved to in-progress. No distinction between temporary vs permanent block; no retry limit or terminal handling.

### 5.3 `get_tasks_by_status` Early Break

- **Location:** `notion_task_reader.py` lines 421-422:
  ```python
  if all_tasks:
      break
  ```
- **Effect:** Stops after the first status that returns tasks; tasks in later statuses may never be fetched.

---

## 6. Exact Files / Functions Involved

| File | Function / Line | Role |
|------|-----------------|------|
| `backend/app/services/notion_task_reader.py` | `get_pending_notion_tasks` L213-410 | Intake filters; excludes in-progress/investigating |
| `backend/app/services/notion_task_reader.py` | `get_tasks_by_status` L436-523 | Early break bug at L421-422 |
| `backend/app/services/agent_task_executor.py` | `prepare_next_notion_task` L396-458 | Claims task → in-progress |
| `backend/app/services/agent_task_executor.py` | `execute_prepared_notion_task` L596-1000 | No finally-block to reset on crash |
| `backend/app/services/agent_recovery.py` | `run_recovery_cycle` L698-713 | No in-progress/investigating playbook |
| `backend/app/services/agent_scheduler.py` | `start_agent_scheduler_loop` L336-399 | Invokes recovery each cycle |

---

## 7. Operational Risks

- Tasks stuck in in-progress indefinitely after agent/worker crash
- Blocked tasks repeatedly picked without resolution path
- Inconsistent task distribution when `get_tasks_by_status` early-breaks
- Silent failures in status transitions (logging gaps)

---

## 8. Proposed Fix

1. **Add stale in-progress/investigating recovery playbook** in `agent_recovery.py`:
   - Query tasks in `in-progress`, `investigating` older than N minutes (e.g. 30)
   - If no investigation artifact exists → reset to `planned`, clear approval state
   - Max 1 attempt per task (activity log)

2. **Fix `get_tasks_by_status`** in `notion_task_reader.py`:
   - Remove early break; collect from all requested statuses
   - Deduplicate by task id

3. **Improve logging** for skip/retry/blocked reasons in scheduler and recovery

4. **Blocked handling (optional):** Add env `AGENT_BLOCKED_RETRY_ENABLED`; when false, exclude blocked from pickable. Default true to preserve current behavior.

---

## 9. Why the Fix Will Work

- **Stale playbook:** Tasks in in-progress/investigating with no artifact are orphaned. Resetting to planned allows the next intake cycle to pick them. One attempt per task prevents loops.
- **get_tasks_by_status fix:** Ensures `continue_ready_for_patch_tasks` and recovery can fetch tasks from all relevant statuses.
- **Logging:** Makes debugging and monitoring straightforward.

---

## 10. Verification Plan

1. Run diagnostic script: `cd backend && python scripts/diagnose_stuck_notion_tasks.py`
2. Manually create a task, claim it (in-progress), kill agent before execution; confirm recovery resets it within 30 min
3. Check logs for `recovery_stale_in_progress_attempt`

---

## Scenario Simulation

| Scenario | Current | Broken | After Fix |
|----------|---------|--------|-----------|
| 1. Task picked, succeeds | planned → in-progress → testing → done | — | Same |
| 2. Task picked, crashes mid-run | Stays in-progress forever | — | Recovery resets to planned after 30 min |
| 3. Task in-progress, worker dies | Never re-picked | — | Recovery resets to planned |
| 4. Task blocked (temporary) | Picked every cycle, moved to in-progress | — | Same (preserved) |
| 5. Task blocked (permanent) | Picked every cycle | — | Optional: exclude when AGENT_BLOCKED_RETRY_ENABLED=false |
| 6. Status mismatch (Notion vs enum) | notion_status_from_display normalizes | — | Same |

---

## Patch Summary

| File | Change |
|------|--------|
| `backend/app/services/agent_recovery.py` | Added `run_stale_in_progress_playbook()` — resets tasks in in-progress/investigating >30 min with no artifact to planned. Invoked from `run_recovery_cycle()`. |
| `backend/app/services/notion_task_reader.py` | Fixed `get_tasks_by_status()` — removed early break; now collects from all requested statuses; deduplicates by task id. |
| `backend/app/services/agent_scheduler.py` | Added `reset` count to recovery_cycle_done log. |
| `backend/scripts/diagnose_stuck_notion_tasks.py` | New diagnostic script. |
| `backend/tests/test_agent_scheduler_notion.py` | Added `TestAgentRecoveryStaleInProgress` tests. |

---

## Verification Steps

1. **Diagnostic:** `cd backend && python scripts/diagnose_stuck_notion_tasks.py` (requires NOTION_API_KEY, NOTION_TASK_DB)
2. **Unit tests:** `cd backend && pytest tests/test_agent_scheduler_notion.py -v -k "stale_in_progress or recovery"`
3. **Live:** Create task → claim (in-progress) → stop agent → wait 30+ min → confirm recovery resets it
4. **Logs:** `grep recovery_stale_in_progress_attempt logs/agent_activity.jsonl`

---

## Migration / Manual Notion Cleanup

For **existing stuck tasks** already in in-progress or investigating:

- **Option A:** Do nothing — recovery will reset them on the next scheduler cycle (within ~35 min: 30 min staleness + 5 min interval).
- **Option B:** Manually in Notion, change Status to "Planned" for tasks that are clearly orphaned.
- **Option C:** Run diagnostic first: `python backend/scripts/diagnose_stuck_notion_tasks.py` to see which tasks are recoverable.

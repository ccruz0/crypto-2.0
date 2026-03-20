# ATP Agent Task Lifecycle Hardening — Deliverable

## Root Cause Confirmation

The previous fix removed "Needs Revision" as a generic fallback for investigation tasks. This hardening validates, enforces, and prevents regression.

**Confirmed behavior:**
- Investigation stuck → ready-for-investigation (retryable) ✓
- Max retries → blocked ✓
- Needs Revision only when explicit metadata exists ✓

## Files Changed

| File | Change |
|------|--------|
| `backend/app/services/task_status_transition.py` | **NEW** — Central transition helper with invariant enforcement |
| `backend/app/services/notion_tasks.py` | Add needs-revision metadata guard to update_notion_task_status |
| `backend/app/services/agent_task_executor.py` | Use safe_transition_to_needs_revision for verification failure |
| `backend/app/services/task_health_monitor.py` | Structured auto_transition logs, Notion comments with from/to/reason |
| `backend/app/services/needs_revision_processor.py` | Structured auto_transition logs for requeue/blocked |
| `backend/app/services/agent_telegram_approval.py` | Needs-revision message: "Why it blocks", "Next step" |
| `backend/tests/test_task_status_transition.py` | **NEW** — Regression tests for invariant |
| `backend/tests/test_task_health_monitor.py` | Updated assertions (already done in prior fix) |

## Invariant Enforcement

**Rule:** A task MUST NOT transition to "needs-revision" unless at least one of:
- `revision_reason`
- `verify_summary`
- `missing_inputs`
- `decision_required`

**Implementation:**
1. `notion_tasks.update_notion_task_status(page_id, "needs-revision", ...)` — requires `needs_revision_metadata` dict with at least one non-empty value. Returns False if missing.
2. `task_status_transition.safe_transition_to_needs_revision()` — the only recommended entry point; validates metadata before calling update.
3. `task_status_transition.transition_task_status()` — when target is needs-revision without valid metadata: logs `invalid_needs_revision_transition`, fallbacks to ready-for-investigation (retryable) or blocked (not retryable).

## Before/After Transition Table

| Trigger | Before | After |
|---------|--------|-------|
| Investigation stuck 15+ min | ready-for-investigation | ready-for-investigation (unchanged) |
| Max retries | blocked | blocked (unchanged) |
| Verification failed (valid) | needs-revision | needs-revision via safe_transition_to_needs_revision |
| Direct update_notion_task_status(..., "needs-revision") | Allowed | **Rejected** unless needs_revision_metadata passed |

## Sample Notion Logs (activity log)

```json
{"timestamp": "2025-03-20T12:00:00.000Z", "event_type": "auto_transition", "task_id": "abc-123", "task_title": "Fix bug X", "details": {"from_status": "investigating", "to_status": "ready-for-investigation", "reason": "Investigation timed out (no progress within threshold). Retrying automatically.", "retryable": true, "user_action_required": false, "retry_attempt": 1}}
```

```json
{"timestamp": "2025-03-20T12:15:00.000Z", "event_type": "auto_transition", "task_id": "abc-123", "details": {"from_status": "patching", "to_status": "blocked", "reason": "Task stuck after 3 automatic retries (operational timeout). No user revision required. Re-queue manually when ready.", "retryable": true, "user_action_required": false}}
```

## Sample Telegram Messages

**Blocked (operational failure):**
```
Task blocked (operational failure).

Title: Fix bug X
Status: Blocked

Reason: Task stuck after 3 automatic retries (operational timeout). No user revision required. Re-queue manually when ready.

[Re-investigate] [View Report]
```

**Needs Revision (verification failed):**
```
⚠️ Solution verification failed

Task: Fix bug X

Why it blocks progress: The patch output does not address the task requirements.

Feedback:
Output does not address task requirements.

Next step: Use Re-investigate to iterate with this feedback.

[Re-investigate] [View Report]
```

## Test Results

```bash
.venv/bin/python -m pytest backend/tests/test_task_health_monitor.py backend/tests/test_task_status_transition.py -v
```

- 25 tests passed
- test_investigation_stuck_moves_to_ready_for_investigation ✓
- test_max_retries_moves_to_blocked_not_needs_revision ✓
- test_needs_revision_without_metadata_rejected ✓
- test_needs_revision_with_metadata_allowed ✓
- test_invalid_needs_revision_fallbacks_to_ready_for_investigation ✓

## Validation Steps

1. **Investigation stuck:** Create task in investigating, set last_edited_time 20+ min ago, run scheduler → status = ready-for-investigation.
2. **Max retries:** Simulate retry_count=3 for patching task → status = blocked.
3. **Verification failure:** Trigger solution verification fail in advance_ready_for_patch_task → status = needs-revision with feedback.
4. **Invalid needs-revision:** Call update_notion_task_status(task_id, "needs-revision") without metadata → returns False.

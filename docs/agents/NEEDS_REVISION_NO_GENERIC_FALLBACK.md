# Needs Revision: No Generic Fallback for Investigation Tasks

## Root Cause

Investigation tasks were moved to "Needs Revision" without any explicit revision request, missing input summary, or user decision being asked. This broke the autonomy flow because the user did not know what to revise.

**Primary bug:** `task_health_monitor.py` moved tasks stuck during investigation (15+ min with no progress) to "Needs Revision" on first detection. This is an **operational failure** (timeout, agent crash, etc.), not a user-action-required case.

**Secondary bug:** When max automatic retries were reached (patching/testing stuck 3 times), tasks were moved to "Needs Revision" instead of "Blocked". Again, this is operational failure — no user revision required.

## Status Transition Table

### Before (buggy)

| Trigger | From Status | To Status | User Action |
|---------|-------------|-----------|-------------|
| Investigation stuck 15+ min | investigating | **needs-revision** | ❌ Unclear — user doesn't know what to revise |
| Max retries (patching/testing) | patching/testing | **needs-revision** | ❌ Unclear |
| Solution verification failed | ready-for-patch | needs-revision | ✅ Explicit feedback in comment |

### After (fixed)

| Trigger | From Status | To Status | User Action |
|---------|-------------|-----------|-------------|
| Investigation stuck 15+ min | investigating | **ready-for-investigation** | None — retried automatically |
| Investigation stuck, retries ≥ 3 | investigating | **blocked** | Re-queue manually when ready |
| Max retries (patching/testing) | patching/testing | **blocked** | Re-queue manually when ready |
| Solution verification failed | ready-for-patch | needs-revision | Re-investigate with feedback (unchanged) |

## When to Use Needs Revision

**Only** when there is an explicit, structured reason requiring user action:

- Solution verification failed (patch does not address task) — feedback in comment
- Missing input (user must provide)
- Ambiguous objective (user must clarify)
- Blocked external dependency requiring user choice
- Approval required

**Never** use Needs Revision for:

- Operational timeouts (investigation stuck)
- Agent crash / no progress
- Max automatic retries reached

## Files Changed

| File | Change |
|------|--------|
| `backend/app/services/task_health_monitor.py` | Investigation stuck → ready-for-investigation; max retries → blocked |
| `backend/app/services/telegram_commands.py` | Allow Re-investigate for blocked tasks (re-queue after operational failure) |
| `backend/tests/test_task_health_monitor.py` | Updated assertions for new transitions |

## Validation Steps

1. **Investigation stuck → retryable:**
   ```bash
   # Create a task in investigating, set last_edited_time 20+ min ago
   # Run scheduler or check_for_stuck_tasks
   # Assert: task moves to ready-for-investigation (not needs-revision)
   ```

2. **Max retries → blocked:**
   ```bash
   # Simulate patching stuck 3 times (retry_count = 3)
   # Assert: task moves to blocked (not needs-revision)
   ```

3. **Verification failure still uses needs-revision:**
   ```bash
   # Trigger solution verification failure in advance_ready_for_patch_task
   # Assert: task moves to needs-revision with explicit feedback
   ```

4. **Run tests:**
   ```bash
   cd backend && python -m pytest tests/test_task_health_monitor.py -v
   ```

## Example: User-Facing Message for "Needs User Input"

When the system truly needs user input (e.g. missing input, ambiguous objective), the message should be structured:

```
Task needs your input

Title: [task title]

Blocker: Missing required input — which exchange account should be used for this order?

Why it blocks progress: The agent cannot proceed without knowing the target account.

Options:
  A) Use binance_main (default)
  B) Use binance_test
  C) Specify a different account

Recommended: A

Reply with your choice or use the Re-investigate button in Telegram to provide more context.
```

## Example: User-Facing Message for "Blocked (Operational)"

```
Task blocked (operational failure)

Title: [task title]
Status: Blocked

Reason: Task stuck after 3 automatic retries (operational timeout). No user revision required. Re-queue manually when ready.

[Re-investigate] [View Report]
```

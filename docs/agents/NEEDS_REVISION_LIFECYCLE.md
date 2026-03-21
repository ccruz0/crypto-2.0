# Needs Revision Lifecycle

Tasks must not remain in "Needs Revision". They must either be fixed and completed (DONE) or escalated with a clear blocker.

## Lifecycle Rules

1. **"Needs Revision" is NOT a terminal state** — it automatically triggers re-execution.
2. **When a task enters "Needs Revision"**, the system:
   - Logs `revision_reason` (what failed)
   - Increments `revision_count`
   - On the next scheduler cycle: either re-runs the task or marks it Blocked
3. **Retry loop**: max 3 revision attempts. After 3 failures → status set to **Blocked** with explicit `blocker_reason`.
4. **Mandatory validation**: DONE is never set without validation passing (enforced in executor).
5. **Observability**: `revision_reason`, `retry_attempt`, `validation_result` are logged to the agent activity log.

## Notion Fields

| Field | Purpose |
|-------|---------|
| **Revision Count** | Number of times the task has entered Needs Revision (0–3). |
| **Revision Reason** | Reason for the last revision (e.g. solution verification failed). |
| **Blocker Reason** | Set when task is Blocked after max revisions; explains why. |

## Flow

```
Task fails (solution verification / stuck)
    → Status: Needs Revision
    → revision_count += 1
    → revision_reason = failure summary

Scheduler cycle:
    → needs_revision_processor runs
    → If revision_count >= 3: Status = Blocked, blocker_reason = "..."
    → Else: Status = Ready for Investigation, clear approval, re-run
```

## Validation

To validate the fix:

1. Pick one "Needs Revision" task in Notion.
2. Run the scheduler (or wait for the next cycle).
3. The system must either:
   - Re-run it and complete it (DONE), or
   - Mark it BLOCKED with an explicit reason after 3 failed attempts.

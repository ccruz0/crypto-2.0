# Task Impact Classifier Fix (Operational/Production-Blocking)

## Context

Telegram `/task` requests describing production-impacting operational issues were sometimes classified as low-impact (status=backlog, priority=low). Terms like "blocks operational task creation", "prevents incident response", "affects agent workflow" were not recognized.

## Root Cause

The value/impact classifier used limited keyword sets:
- `VALUE_IMPACT_KEYWORDS`: production, prod, orders, trading, revenue, live
- `VALUE_FAILURE_KEYWORDS`: error, not working, broken, fails, failing
- No recognition of operational/production-blocking language (blocks, prevents, incident, workflow, intake, affects)

## Fix

1. **Expanded keywords**:
   - `VALUE_FAILURE_KEYWORDS`: added blocks, blocking, prevents
   - `VALUE_OPERATIONAL_KEYWORDS`: operational, incident, workflow, intake, affects, blocks, blocking, prevents
   - `PRIORITY_FAILURE_KEYWORDS`: added blocks, blocking, prevents
   - `PRIORITY_OPERATIONAL_KEYWORDS`: operational, incident, workflow, intake, affects

2. **Value scoring**: Operational keywords add +25 to value score.

3. **Safety pass**: `_value_gate_safety_pass` now returns True for operational keywords, so these tasks are never treated as low-impact.

4. **Logging**: Added `task_compiler_intent`, `task_value_computed`, `task_compiler_impact`, `task_compiler_low_impact` with raw text, scores, and decision reasons.

## Files Changed

- `backend/app/services/task_compiler.py`
- `backend/tests/test_task_value_gate.py`

## Verification (AWS Logs)

```bash
# Raw intent and impact decision
grep "task_compiler_intent" logs/*.log
grep "task_compiler_impact" logs/*.log
grep "task_value_computed" logs/*.log

# Low-impact reasons (when applicable)
grep "task_compiler_low_impact" logs/*.log
```

## Note

The task compiler **never rejects** task creation. Low-impact tasks are created with status=backlog and priority=low. If you see "Task creation failed: This task has low impact and was not created", that error originates from a different code path (not in the current task_compiler). This fix ensures operational/production-blocking tasks get status=planned and higher priority when created.

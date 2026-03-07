# Strategy Patch Callback

Controlled code-changing callback for low-risk business-logic tuning, designed for explicit approval + manual execution only.

Implementation:

- `backend/app/services/agent_strategy_patch.py`
- Functions:
  - `apply_strategy_patch_task(prepared_task: dict) -> dict`
  - `validate_strategy_patch_task(prepared_task: dict) -> dict`

## Eligibility rules

This callback is eligible only when **all** conditions are met:

- task clearly references strategy/business-logic improvement
- analysis artifact exists (`docs/analysis/notion-task-<task_id>.md` or `docs/analysis/signal-performance-<task_id>.md`)
- analysis includes:
  - proposed improvement
  - affected files
  - validation plan
  - risk level
  - confidence score
- risk level is not `high`
- confidence score is `>= 0.60`
- all affected files are in the strict allowlist

If not eligible, apply returns:

```json
{
  "success": false,
  "summary": "task not eligible for strategy patch callback"
}
```

## File allowlist

Only these file patterns are patchable:

- `backend/app/services/signal_monitor.py`
- `backend/app/services/alert_*.py`
- `backend/app/services/indicator_*.py`

Anything outside this allowlist is rejected.

## Allowed change types

Small, localized, auditable changes only, such as:

- numeric threshold tuning
- lookback window tuning
- volume multiplier/filter tuning
- enabling an additional simple filter condition
- adjusting existing condition constants

## Forbidden change types

Not allowed:

- structural refactors
- new subsystems/dependencies/connectors
- new API/network calls
- execution/order-placement logic changes
- exchange sync changes
- DB schema changes
- deploy/nginx/docker/runtime/infra changes
- `telegram_commands.py` changes

## Manual-only execution requirement

- callback selection marks strategy patch as `manual_only`
- scheduler auto-execution is disabled for manual-only callbacks
- execution must remain explicit via approval + manual trigger (`Execute Now`)

## Patch note output

- patch note: `docs/analysis/patches/notion-task-<task_id>.md`
- index: `docs/analysis/patches/README.md`

Patch note includes:

- task id
- current/proposed version
- affected files
- exact parameters changed
- rationale
- validation plan
- risk level
- confidence score
- touched line summary

## Versioning and traceability

Patch callback keeps versioning fields in-flow:

- proposed version and change summary remain attached to execution metadata
- approval/release flow continues using existing versioning/release mechanics

This callback is intentionally minimal and constrained to reduce patch risk while enabling concrete, auditable improvements.

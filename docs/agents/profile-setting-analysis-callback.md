# Profile Setting Analysis Callback

Analysis-only callback for per-symbol, per-profile, per-side setting proposals.

Implementation:

- `backend/app/services/profile_setting_analysis.py`
- Functions:
  - `apply_profile_setting_analysis_task(prepared_task: dict) -> dict`
  - `validate_profile_setting_analysis_task(prepared_task: dict) -> dict`

## When this callback is selected

Selected only when task metadata clearly indicates profile-setting intent, e.g.:

- per-coin settings
- profile tuning
- conservative/aggressive/scalp/intraday optimization
- buy/sell setting tuning
- per-symbol parameter tuning
- preset optimization
- profile-based false positives/false negatives
- profile-based signal quality

If task is not clearly eligible, apply returns:

```json
{
  "success": false,
  "summary": "task not eligible for profile setting analysis callback"
}
```

## What data it reads

Local/project sources only:

- docs under `/docs` (business intent context)
- profile/setting code paths (`config_loader`, `strategy_profiles`, `signal_monitor`)
- local data artifacts if present (sqlite, runtime-history, logs)
- existing model/config naming and metadata

No external services or connectors are added.

## Symbol/profile/side inference

Targets are inferred from:

- task text and metadata
- naming conventions in code/config

If symbol, profile, or side cannot be inferred confidently, report marks them as `unknown (uncertain)` instead of failing.

## Output file

- report: `docs/analysis/profile-settings-<task_id>.md`
- index: `docs/analysis/README.md`

## Confidence score heuristic

Rule-based score in `[0.0, 1.0]` using:

- historical data availability/sample coverage
- mapping clarity of symbol/profile/side
- observed pattern strength
- directness of proposed setting changes
- missing-data penalties

The report includes a short explanation of this heuristic.

## Version proposal integration

Uses existing versioning helper and includes:

- `current_version`
- `proposed_version`
- `version_status = proposed`
- `change_summary`

## Safety and traceability

- Analysis-only; no production code changes.
- No trading execution/order placement/exchange sync/deploy/infra/runtime edits.
- Runs behind approval gate and manual-only callback handling.
- Fits existing proposal/approval/release traceability and activity logging.

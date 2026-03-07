# Signal Performance Analysis Callback

Analysis-only callback focused on historical signal outcomes and precision improvements.

Implementation:

- `backend/app/services/signal_performance_analysis.py`
- Functions:
  - `apply_signal_performance_analysis_task(prepared_task: dict) -> dict`
  - `validate_signal_performance_analysis_task(prepared_task: dict) -> dict`

## When this callback is selected

Selected only when task metadata clearly indicates:

- signal performance
- signal quality
- historical signal review
- false positives / false negatives
- threshold tuning
- volume filter tuning
- lookback tuning
- trend confirmation tuning
- alert precision improvement

If not clearly eligible, apply returns:

```json
{
  "success": false,
  "summary": "task not eligible for signal performance analysis callback"
}
```

## What data it reads

Local/project data only (no external connectors), such as:

- signal-related model/service files
- available sqlite records already present in the repo
- runtime history directory
- local logs
- existing order/history artifacts available on disk

If a metric cannot be computed due to missing fields/data, the analysis explicitly reports it as unavailable.

## What file it writes

- report: `docs/analysis/signal-performance-<task_id>.md`
- index: `docs/analysis/README.md` (create/update)

## Confidence score heuristic

Rule-based score in `[0.0, 1.0]`, based on:

- historical sample count (more samples -> higher confidence)
- segment separation strength (larger success-rate deltas -> higher confidence)
- direct mapping between observed problem and proposed improvement (small boost)
- missing key data (penalty)

## Version proposal integration

Uses existing versioning helper and includes:

- `current_version`
- `proposed_version`
- `version_status = proposed`
- `change_summary`

## Safety and traceability

- Analysis-only output; does not change production code or trading execution behavior.
- No deployment, infra, runtime-config, nginx/docker, or order-placement changes.
- Intended to remain behind the approval gate for signal/strategy-sensitive tasks.
- Fits current proposal/approval/release traceability via approval summary, activity events, and version metadata.

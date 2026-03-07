# Strategy Analysis Callback

Analysis-first callback for business-logic improvement proposals around strategy, signals, and alerts.

Implementation:

- `backend/app/services/agent_strategy_analysis.py`
- Functions:
  - `apply_strategy_analysis_task(prepared_task: dict) -> dict`
  - `validate_strategy_analysis_task(prepared_task: dict) -> dict`

## When this callback is selected

Selected only when task metadata clearly indicates topics like:

- alert logic
- signal quality
- thresholds
- historical trend analysis
- false positives / false negatives
- business-logic alignment
- volume filters
- indicator tuning
- lookback window tuning

If not clearly eligible, the apply callback returns:

```json
{
  "success": false,
  "summary": "task not eligible for strategy analysis callback"
}
```

## What data it reads

The callback reads existing repository/local data only:

- `/docs` context (architecture, agents, integrations, relevant area docs)
- relevant backend source files (strategy/signal/alert related)
- available historical sources already present in the project (for example local logs, runtime history directories, order/signal models, and history DB access code if present)

No external services are added in this step.

## What file it writes

- Analysis output: `docs/analysis/notion-task-<task_id>.md`
- Index file: `docs/analysis/README.md`

## Required analysis sections

Each generated note includes:

- Title
- Task ID
- Current Version
- Proposed Version
- Problem Observed
- Current Implementation Summary
- Business Logic Intent
- Historical Data Observations
- Proposed Improvement
- Expected Benefit
- Affected Files
- Validation Plan
- Risk Level

## Version proposal integration

The callback uses the existing versioning helper (`build_version_summary`) and includes:

- `current_version`
- `proposed_version`
- `version_status = proposed`
- `change_summary`

Returned structured payload also includes:

- `success`
- `summary`
- `analysis_file`
- `proposed_version`
- `change_summary`
- `affected_files`
- `validation_plan`
- `risk_level`

## Safety and scope

- Analysis-only behavior; no production code edits are performed by this callback.
- No shell commands, deployment, infra changes, or runtime configuration changes.
- Designed to remain behind the existing approval gate for strategy/signal related tasks.

## Approval / execution / release traceability fit

This callback generates a concrete analysis proposal that feeds existing workflow traceability:

- Approval summary/Telegram can show proposal type + proposed version + short summary.
- Notion/version metadata remains at proposal stage until explicitly approved and released.
- Activity log can record analysis generation and validation failures.
- Changelog/release traceability continues to rely on the existing versioning/release flow.

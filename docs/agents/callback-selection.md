# Callback selection (agents)

This document describes callback packs used by the injected execution design:

- low-risk documentation/triage callbacks
- analysis-only strategy/signal proposal callback (approval-gated)
- analysis-only historical signal-performance callback (approval-gated)
- analysis-only profile-setting callback (approval-gated)
- controlled strategy patch callback (approval-gated, manual-only)

The callback implementations live in `backend/app/services/agent_callbacks.py`. Whether a task may run **without human approval** is decided by the [human approval gate](human-approval-gate.md); documentation and monitoring triage callbacks are treated as low-risk and may run automatically when the gate says approval is not required.

---

## Why this exists

We already have:

- Notion task intake + prioritization (`notion_task_reader.py`)
- Claiming + preparation plan (`prepare_next_notion_task`)
- Controlled execution with injected callbacks (`execute_prepared_notion_task`)
- Safe status transitions aligned to canonical lifecycle (`planned → in-progress → investigation-complete → ready-for-patch → patching → awaiting-deploy-approval → deploying → done/blocked`)

This step connects **real callbacks** for a narrow, low-risk subset of tasks so the workflow can prove itself end-to-end without risking production trading behavior.

---

## Eligible task categories (supported now)

### 1) Documentation tasks (low risk)

Eligible when the task looks documentation-related based on simple keywords across:
- task title
- project
- type
- inferred repo area name

Keywords include: `doc`, `docs`, `documentation`, `runbook`, `readme`, `agent`.

**Apply behavior** (`apply_documentation_task`):
- Creates a short note under `docs/agents/generated-notes/notion-task-<id>.md`
- Updates `docs/agents/generated-notes/README.md` to reference it
- Includes placeholders only (triage summary checklist); does not invent large content

**Validate behavior** (`validate_documentation_task`):
- Confirms the note exists and is non-empty
- Validates that any *relative* markdown links in the note resolve to existing files

---

### 2) Monitoring triage tasks (low risk)

Eligible when the task looks monitoring/ops related based on keywords or inferred area:
- inferred rule match: `monitoring-infra`
- or keywords: `monitor`, `monitoring`, `health`, `incident`, `infrastructure`, `ops`, `nginx`, `502`, `504`, `ssm`, `ec2`, `docker`

**Apply behavior** (`apply_monitoring_triage_task`):
- Creates a short incident/triage note under `docs/runbooks/triage/notion-triage-<id>.md`
- Updates `docs/runbooks/triage/README.md` to reference it
- Includes inferred modules/docs/runbooks and short “next steps” checklist
- Does **not** change runtime logic

**Validate behavior** (`validate_monitoring_triage_task`):
- Confirms the triage note exists and is non-empty
- Confirms it includes sections: Affected modules, Relevant docs, Next steps
- Confirms it includes at least one concrete module/doc reference
- Validates relative markdown links (if present)

---

### 3) Strategy/signal improvement analysis tasks (approval-gated)

Eligible when task metadata clearly indicates topics such as:

- alert logic
- signal quality
- thresholds
- historical trend analysis
- false positives / false negatives
- business-logic alignment
- volume filters
- indicator tuning
- lookback window tuning

**Apply behavior** (`apply_strategy_analysis_task`):
- Reads docs context + relevant backend files + available local historical sources
- Generates an analysis proposal note at `docs/analysis/notion-task-<id>.md`
- Updates/creates index `docs/analysis/README.md`
- Includes version proposal metadata (`current_version`, `proposed_version`, `change_summary`, `version_status=proposed`)
- Does **not** modify production runtime logic

**Validate behavior** (`validate_strategy_analysis_task`):
- Confirms the analysis note exists and is non-empty
- Confirms all required sections are present
- Confirms at least one affected file and one concrete proposed improvement
- Validates relative markdown links (if present)

Because these tasks are strategy/signal related, they remain behind the existing approval gate.

---

### 4) Signal performance analysis tasks (approval-gated)

Eligible when task metadata clearly indicates:

- signal performance
- signal quality
- historical signal review
- false positives / false negatives
- threshold tuning
- volume filter tuning
- lookback tuning
- trend confirmation tuning
- alert precision improvement

**Apply behavior** (`apply_signal_performance_analysis_task`):
- Uses local historical sources when available (models/files, sqlite signal tables, runtime-history, logs)
- Computes best-effort performance metrics and segment observations
- Reports unavailable metrics explicitly when data fields are missing
- Generates analysis report at `docs/analysis/signal-performance-<id>.md`
- Updates/creates `docs/analysis/README.md`
- Includes version proposal metadata and confidence score

**Validate behavior** (`validate_signal_performance_analysis_task`):
- Confirms file exists and is non-empty
- Confirms required sections exist
- Confirms at least one data source, one proposed improvement, one affected file, and confidence score are present
- Validates relative markdown links (if present)

Because this is signal-domain analysis, it remains behind the existing approval gate.

---

### 5) Strategy patch tasks (approval-gated, manual-only)

Selected only when strict runtime eligibility checks pass, including:

- matching strategy/business-logic improvement intent
- existing analysis artifact with required sections
- non-high risk level
- confidence score `>= 0.60`
- all affected files inside strict allowlist

**Apply behavior** (`apply_strategy_patch_task`):
- Reads analysis artifact metadata and validates constraints
- Applies tiny, explicit, audited patch transformations only in allowlisted files
- Fails safely if expected patterns are missing or ambiguous
- Writes patch note at `docs/analysis/patches/notion-task-<id>.md`
- Updates/creates `docs/analysis/patches/README.md`

**Validate behavior** (`validate_strategy_patch_task`):
- Confirms patch note exists and has required sections
- Confirms modified files exist and are allowlisted
- Confirms patch is localized and non-empty (touched-line summary)
- Confirms no non-allowlisted file is listed/modified by note

This callback is explicitly **manual-only** and must not auto-execute in scheduler.

---

### 6) Profile-setting analysis tasks (approval-gated)

Eligible when task metadata clearly indicates:

- per-coin/per-symbol settings tuning
- preset/profile optimization (conservative/aggressive/scalp/intraday)
- buy/sell-side setting tuning
- profile-based signal quality and false-positive/false-negative review

**Apply behavior** (`apply_profile_setting_analysis_task`):
- Infers target symbol/profile/side from task metadata and naming conventions
- Reads local docs, config/profile code, and available local historical sources
- Generates analysis report at `docs/analysis/profile-settings-<id>.md`
- Updates/creates `docs/analysis/README.md`
- Includes version proposal metadata and confidence score
- Marks uncertain targets explicitly instead of failing when inference is incomplete

**Validate behavior** (`validate_profile_setting_analysis_task`):
- Confirms report exists, is non-empty, and includes all required sections
- Confirms symbol/profile/side are present (or explicitly uncertain)
- Confirms concrete proposed setting changes or explicit safe no-numeric rationale
- Confirms confidence score and affected files exist
- Validates relative markdown links (if present)

This callback is analysis-only and remains behind approval/manual execution flow.

---

## Intentionally NOT eligible yet (unsupported)

To keep this safe, the following are intentionally excluded from callbacks in this step:

- Trading execution paths (exchange orders, order placement, SL/TP behavior)
- Order lifecycle and history sync changes
- Deployment-heavy infrastructure changes
- Any callback that runs shell commands, deploy scripts, or modifies production runtime

Reason: these areas can cause real financial/production impact. The workflow should first be proven on documentation/triage tasks where the risk is minimal.

---

## How selection works

Use `select_default_callbacks_for_task(prepared_task)` to pick a safe default pack:

- Documentation-like tasks → documentation callbacks
- Monitoring/infrastructure triage tasks → monitoring triage callbacks
- Signal-performance analysis tasks → signal-performance-analysis callbacks (analysis-only proposal)
- Profile-setting analysis tasks → profile-setting-analysis callbacks (analysis-only proposal)
- Strategy/signal analysis tasks → strategy-analysis callbacks (analysis-only proposal)
- Strategy patch tasks → strategy-patch callbacks (manual-only allowlisted tuning)
- Everything else → no callbacks selected (`apply_change_fn=None`, `validate_fn=None`)

The selection is intentionally **rule-based and conservative**. If a task is ambiguous, it is treated as ineligible and no callbacks are selected.

---

## Approval gate

Tasks that get **documentation** or **monitoring triage** callbacks are typically **low-risk** and may be executed without explicit human approval (see [human-approval-gate.md](human-approval-gate.md)). Strategy/signal analysis callbacks are intentionally treated as approval-gated due domain sensitivity. Any other callback selection, or tasks whose title/details/area indicate trading, order, exchange, or deploy, **require approval** before execution. Use `prepare_task_with_approval_check()` and `execute_prepared_task_if_approved()` to respect the gate.

---

## Minimal integration example

```python
from app.services.agent_task_executor import prepare_task_with_approval_check, execute_prepared_task_if_approved

bundle = prepare_task_with_approval_check()
if bundle and bundle.get("prepared_task", {}).get("claim", {}).get("status_updated"):
    # If approval["required"] is False, execution runs; if True, pass approved=True after human approval.
    out = execute_prepared_task_if_approved(bundle, approved=bundle.get("approval", {}).get("required") is False)
```


# Governance layer — implementation notes

**Env (summary):** `ATP_GOVERNANCE_ENFORCE` — blocks monitoring backend restart on AWS. **`ATP_GOVERNANCE_AGENT_ENFORCE`** — on AWS, release-candidate **Approve Deploy** and **agent task Approve** (for `prod_mutation` callbacks) use governance manifests + `governance_executor` (see below).

**Path guard (LAB):** `ATP_PATH_GUARD_DISABLE` — emergency bypass for `path_guard` (see [PATH_GUARD_DESIGN.md](./PATH_GUARD_DESIGN.md)). `PATH_GUARD_LOG_ALLOWED` — INFO log every allowed write. `ATP_PATH_GUARD_EXTRA_ALLOWED_PREFIXES` — extra allowed roots (comma-separated).

## What was added

- **LAB path guard** (`backend/app/services/path_guard.py`): centralized allow/deny for OpenClaw/LAB file writes. Allowed: resolved paths under `<workspace>/docs/**` plus configured artifact fallbacks (`AGENT_*_DIR`, `/tmp/agent-*`, optional `ATP_PATH_GUARD_EXTRA_ALLOWED_PREFIXES`). Blocked: workspace paths outside `docs/`, and paths outside workspace that are not under those fallbacks. APIs: `safe_write_text`, `safe_write_bytes`, `safe_append_text`, `safe_mkdir_lab`, `safe_open_text`, `assert_writable_lab_path`, `assert_lab_patch_target`. Design: [PATH_GUARD_DESIGN.md](./PATH_GUARD_DESIGN.md). Runbook: [path_guard_operations.md](../runbooks/path_guard_operations.md).
- **Path guard static audit** (`backend/scripts/path_guard_audit.py`): scans `app/services` for (1) `.write_text` / `.write_bytes` / `open(..., 'w'|'a'|...)` with existing severity rules, and (2) **in `LAB_ENFORCED` files only** — `shell=True`, `os.system(`, `asyncio.create_subprocess_shell(`, string-form `subprocess.run("` / `Popen("`. List-argv subprocess without `shell=True` is **not** flagged (staging git/cursor/pytest). No scan for `>` / `tee` inside string literals (too noisy / needs parser). Tests: `backend/tests/test_path_guard_audit.py`.
- **CI:** GitHub Actions workflow [`.github/workflows/lab-path-guard-audit.yml`](../../.github/workflows/lab-path-guard-audit.yml) runs `python scripts/path_guard_audit.py --fail-on-lab-bypass --ci` from `backend/` on every PR/push to `main`. **Enforced:** error-level hits in `LAB_ENFORCED` files (raw writes **or** risky subprocess patterns above). **Advisory:** `warn`/`info` hits do not fail the job; scripts are not scanned in CI unless you run locally with `--include-scripts`. **Unrelated:** [`.github/workflows/path-guard.yml`](../../.github/workflows/path-guard.yml) is a separate gate (PR diff must not touch a fixed list of trading/deploy paths).
- **Tables** (PostgreSQL migration + SQLAlchemy models): `governance_tasks`, `governance_events`, `governance_manifests`.
- **Service** (`backend/app/services/governance_service.py`): lifecycle states, allowed transitions, manifest digest (`sha256:` + canonical JSON of `commands`, `scope_summary`, `risk_level`), approval with TTL, invalidation on digest mismatch or superseding approval, structured events (`plan`, `action`, `finding`, `decision`, `result`, `error`) persisted to DB and mirrored to `logs/agent_activity.jsonl` via `log_agent_event(..., details={"governance": envelope})`.
- **Executor** (`backend/app/services/governance_executor.py`): runs **only** whitelisted steps after `is_manifest_approved_and_valid(..., expected_commands=...)`.
- **API** (`backend/app/api/routes_governance.py`), mounted at `/api/governance/*`.
- **Task timeline (read model)** (`backend/app/services/governance_timeline.py`): merged **read-only** view for one task — `GET /api/governance/tasks/{task_id}/timeline`, `GET /api/governance/by-notion/{page_id}/timeline`. Uses existing tables only; exposes `coverage` flags for partial/legacy linkage. Each timeline item includes optional **`signal`** (`failed` \| `drift` \| `classification_conflict` \| `blocked`) plus top-level **`signal_counts`**. **`resolve_timeline_event_signal`** prefers **`payload_json.signal_hint`** when set at emission time (`emit_error_event` / `emit_decision_event` / `emit_result_event` optional `signal_hint=`); otherwise **`derive_timeline_event_signal`** pattern-matches as before. **No DB migration** — hint lives inside existing JSON. **Not a lifecycle engine** — hints improve operator clarity incrementally; historical events and unannotated paths still use derivation only. See [CONTROL_PLANE_TASK_VIEW.md](./CONTROL_PLANE_TASK_VIEW.md) and [trace_task_end_to_end.md](../runbooks/trace_task_end_to_end.md).
- **Agent-path timeline visibility** (`governance_service.emit_visibility_error_if_governance_task_exists` + `agent_task_executor`): when a **`governance_tasks`** row already exists for `gov-notion-<notion_page_id>`, high-signal operator cases also persist a **`governance_events`** `error` row with explicit **`payload.signal_hint`**: **`classification_conflict`** (execute-prepared classification gate), **`blocked`** (manifest not approved / invalid / digest mismatch at that gate), **`drift`** (bundle fingerprint drift with enforce blocking execution in `execute_prepared_task_if_approved`). **If the task row is missing, no row is emitted** (logs / JSONL remain the audit trail). Execution and fail-closed policy are unchanged.
- **Early governance task shell (AWS + `ATP_GOVERNANCE_AGENT_ENFORCE` only):** `governance_agent_bridge.ensure_notion_governance_task_stub` creates **`gov-notion-<page_id>`** with `source_type=notion_agent` **without** creating a manifest or changing approval state. Wired from **`prepare_next_notion_task` / `prepare_task_by_id`** (after a successful Notion claim) and **`send_task_approval_request`** (after quiet-mode check, **before** classification preflight) so resolver/timeline APIs and visibility emissions usually have a correlation row **before** `ensure_agent_execute_prepared_manifest` / `ensure_agent_deploy_manifest`. **`governance_task_has_plan_event`** + conditional **`emit_plan_event`** in those ensure functions keep a single narrative **plan** row when the task was pre-created. **Manifest rows still mean execution authorization** (digest + approval), not “task exists.”
- **Enforcement** (`backend/app/services/governance_enforcement.py`): blocks `POST /api/monitoring/backend/restart` when `ATP_GOVERNANCE_ENFORCE=true` and `ENVIRONMENT=aws`.
- **Telegram** (`backend/app/services/governance_telegram.py`): short summaries on awaiting approval, approve/deny, completed/failed (Claw channel; respects `RUN_TELEGRAM`).
- **Agent bridge** (`backend/app/services/governance_agent_bridge.py`): ties **release-candidate deploy** and **`execute_prepared_notion_task` (prod_mutation only)** to governance tasks/manifests when `ATP_GOVERNANCE_AGENT_ENFORCE=true` on AWS.
- **Read-only control-plane UI** (`frontend/src/app/governance/task/page.tsx`, `frontend/src/lib/governanceTaskView.ts`): `/governance/task` — resolve + timeline, **signal** filters, **Important only**, jump-to-latest (with filter auto-adjust for signal targets), **Copy** / links, and per-row **expand** for **`compact_payload`** / **`links`** / **`payload_ref`** (no writes, no extra API). See [CONTROL_PLANE_TASK_VIEW.md](./CONTROL_PLANE_TASK_VIEW.md).

## Why separate from `agent_approval_states`

`agent_approval_states` stores **Notion agent** prepared bundles and Telegram approve/deny for **execution / retry** of prepared work. For **PROD deploy** when `ATP_GOVERNANCE_AGENT_ENFORCE=true`, the **source of truth for what runs** is `governance_manifests.digest` + `governance_executor`. The same Telegram button still approves the human intent, but the backend records **`approve_manifest`** and runs **`execute_governed_manifest`** so patch + GitHub dispatch only run after digest validation.

## Agent / OpenClaw deploy path (wired)

| Step | Component |
|------|-----------|
| Manifest created | `send_release_candidate_approval` → `_send_release_candidate_or_deploy_approval` when `use_release_candidate_format` and `ATP_GOVERNANCE_AGENT_ENFORCE` + AWS |
| Manifest storage | `governance_agent_bridge.ensure_agent_deploy_manifest` → `TradingSettings` key `governance_deploy_manifest:<notion_task_id>` |
| Governance task id | `gov-notion-<notion_page_id>` |
| Telegram Approve Deploy | `telegram_commands._handle_extended_approval_callback` → `approve_manifest` + `execute_governed_manifest` (skips legacy patch/deploy) |
| Executor step | `agent_deploy_bundle`: `apply_prepared_strategy_patch_after_approval` then `trigger_deploy_workflow` |

**Legacy deploy** (manifest not required): `ATP_GOVERNANCE_AGENT_ENFORCE` unset/false, or non-AWS `ENVIRONMENT` — same as before (direct patch + `trigger_deploy_workflow`).

## Protected execution paths (today)

| Path | Behavior when `ATP_GOVERNANCE_ENFORCE=true` on AWS |
|------|-----------------------------------------------------|
| `POST /api/monitoring/backend/restart` | **403** — use governed flow |
| `POST /api/governance/execute` | Allowed only with **approved, unexpired** manifest whose digest matches stored commands |

| Path | Behavior when `ATP_GOVERNANCE_AGENT_ENFORCE=true` on AWS |
|------|-----------------------------------------------------------|
| Telegram **Approve Deploy** (release candidate) | Requires prior manifest from approval send; runs **only** via `governance_executor` (`agent_deploy_bundle`) |
| Legacy patch + `trigger_deploy_workflow` in `approve_deploy` | **Not used** when agent enforce is on |
| **`execute_prepared_notion_task`** when callback class is **`prod_mutation`** (`agent_execution_policy`) | Requires execution manifest + `approve_manifest`; runs **only** via `governance_executor` (`agent_execute_prepared_pipeline`) |
| **`execute_prepared_notion_task`** for **patch_prep / read_only / safe_ops** classes | **No** execution manifest; same as before (investigation / docs-only work) |

## Agent execute_prepared pipeline (wired)

| Step | Component |
|------|-----------|
| Governance task shell (optional) | After successful Notion **prepare** claim, or at start of **`send_task_approval_request`** (enforce on): **`ensure_notion_governance_task_stub`** — row only, no manifest |
| Classify | `agent_execution_policy.classify_callback_action` — only **`prod_mutation`** is governed on this path |
| Manifest at Telegram send | `send_task_approval_request` → `ensure_agent_execute_prepared_manifest` (fail-closed if DB/manifest fails) |
| Storage | `TradingSettings` key `governance_execute_manifest:<notion_task_id>` |
| Telegram **Approve** (agent task) | `record_approval` → `approve_manifest` for that `manifest_id` (in addition to `agent_approval_states`) |
| Run | `execute_prepared_notion_task` → `_maybe_run_execute_prepared_through_governance` → `execute_governed_manifest` |
| Executor step | `agent_execute_prepared_pipeline`: loads approved bundle, sets `_governance_pipeline_internal`, calls `execute_prepared_task_if_approved(..., approved=True)` |
| Bypass visibility | When `prod_mutation` runs **without** governance: `log_agent_event("governance_bypassed_legacy_path", ...)` if enforce is off or not AWS |

**Fail-closed (enforce on):** missing `SessionLocal`, manifest create failure, or missing/invalid/unapproved manifest → structured failure on `execute_prepared_notion_task` (no inline apply).

**Unified timeline:** the three cases above additionally write **`governance_events`** (when the governance task row exists) so **`signal_hint`** appears on the task timeline without relying on log-derived inference. Structured logging and `logs/agent_activity.jsonl` remain the secondary, full audit.

## Callback classification (`agent_execution_policy.classify_callback_action`)

This is the **governance gate input** for `execute_prepared_notion_task` when `ATP_GOVERNANCE_AGENT_ENFORCE=true` on AWS: only `prod_mutation` requires an execution manifest. **False negatives (unsafe → patch_prep) are unacceptable.**

### Inputs used (in order)

| Signal | Source |
|--------|--------|
| Explicit class | `callback_selection["governance_action_class"]` = `patch_prep` \| `prod_mutation` — set on **every** pack returned by `select_default_callbacks_for_task` |
| PROD marker | Callable attribute `ATP_GOVERNANCE_PROD_MUTATION_APPLY` (e.g. `apply_strategy_patch_task`, `apply_profile_setting_analysis_task`) |
| Safe lab marker | Callable attribute `ATP_GOVERNANCE_SAFE_LAB_APPLY` (OpenClaw `_apply` closures from `_make_openclaw_callback`; doc-only fallbacks on `agent_callbacks`) |
| Module allowlists | `(module, __name__)` in `_PROD_APPLY_MODULES` / `_SAFE_APPLY_MODULES` in `agent_execution_policy.py` |
| No `apply_change_fn` | `selection_reason` keyword heuristics only (strategy-patch, bug investigation, …) — same as legacy |
| AWS + apply + none matched | **`prod_mutation`** + WARNING log `classification_uncertain_defaulted_to_prod_mutation` (fail-safe) |
| Local (`ENVIRONMENT` not `aws`) | After structural steps, legacy `selection_reason` substring rules for remaining cases |

### Observability

- **INFO:** `governance_classification_result` with `classification_result`, `final_classification`, `is_prod_mutation`, `selection_reason`, `apply_module` / `apply_name`, `callback_module` / `callback_name`, `explicit_class`, `safe_lab_marker`, `prod_mutation_marker`, `enforcement_active`, `environment`, `classification_path`, optional `log_context` (`execute_prepared_gate`, `send_task_approval_request`, `record_approval`, …).
- **WARNING:** `classification_uncertain_defaulted_to_prod_mutation` when AWS cannot prove safety (JSON payload includes `environment`, `enforcement_active`, `callback_module` / `callback_name`, `final_classification`, etc.).
- **WARNING / ERROR:** `governance_classification_conflict` when metadata is contradictory (see below). ERROR when the conflict blocks execution on AWS with agent enforce; WARNING when resolving to fail-safe `prod_mutation` locally or when blocking Telegram approval preflight.

### Classification conflicts (metadata inconsistency)

`validate_governance_classification_inputs` cross-checks explicit `governance_action_class` against callable markers (`ATP_GOVERNANCE_PROD_MUTATION_APPLY`, `ATP_GOVERNANCE_SAFE_LAB_APPLY`) and `(module, __name__)` allowlists. A **conflict** exists when:

| `conflict_type` | Meaning |
|-----------------|--------|
| `dual_safe_lab_and_prod_mutation_markers` | The same apply callable sets both marker attributes. |
| `dual_allowlist_membership` | Identity appears in both `_PROD_APPLY_MODULES` and `_SAFE_APPLY_MODULES` (should never happen). |
| `explicit_patch_prep_vs_structural_prod` | Bundle says `patch_prep` but the callable/identity is prod-marked or on the prod allowlist. |
| `explicit_prod_mutation_vs_structural_safe` | Bundle says `prod_mutation` but the callable/identity is safe-lab-marked or on the safe allowlist. |

**AWS + `ATP_GOVERNANCE_AGENT_ENFORCE`:** `classify_callback_action` raises `GovernanceClassificationConflictError` (no guess). `execute_prepared_notion_task` returns a structured failure with `governance.error=classification_conflict`. When **`governance_tasks`** already has `gov-notion-<page_id>`, an **`error`** governance event is stored with **`signal_hint=classification_conflict`** (otherwise logs/JSONL only). Telegram `send_task_approval_request` / `record_approval` refuse to send or record approval when enforce is on (preflight uses the same validation).

**Local / non-enforced AWS:** conflict is logged (`governance_classification_conflict`, resolution `fail_safe_prod_mutation`) and classification returns **`prod_mutation`** so the task stays behind approval gates rather than being treated as patch-prep.

### Runtime audit (logs)

Script: `backend/scripts/classification_audit_report.py`

```bash
python backend/scripts/classification_audit_report.py /var/log/atp/backend.log
# or
grep governance_classification /var/log/atp/backend.log | python backend/scripts/classification_audit_report.py
python backend/scripts/classification_audit_report.py --sample
```

Parses JSON payloads for `governance_classification_result`, `governance_classification_conflict`, and `classification_uncertain_defaulted_to_prod_mutation`, then prints counts and top `selection_reason` / callback names.

### Persistence

`agent_telegram_approval._serialize_prepared_bundle` stores:

- `governance_action_class` (legacy merge on deserialize when re-selection omits it)
- **`bundle_identity`** — JSON snapshot of execution identity (see below)
- **`bundle_fingerprint`** — `sha256:` + hex over canonical JSON of `bundle_identity`

`load_prepared_bundle_for_execution` deserializes with **`execution_load=True`**: when `bundle_fingerprint` is present, **Notion task type refresh is skipped** so `select_default_callbacks_for_task` sees the same stored `prepared_task` shape as at approval time (reduces routing drift). Rows **without** a fingerprint keep the old Notion refresh behavior.

### Approved bundle identity + drift (`agent_bundle_identity.py`)

**Frozen fields** in `bundle_identity` (used for fingerprinting):

| Field | Role |
|-------|------|
| `notion_task_id` | Task page id |
| `execution_mode` | From `prepared_task` / task |
| `governance_action_class` | `patch_prep` / `prod_mutation` |
| `selection_reason` | Callback pack reason string |
| `manual_only` / `extended_lifecycle` | Extended lifecycle flag (from `manual_only`) |
| `apply` / `validate` / `deploy` | `{module, name}` per callable (or null) |

**Helpers:** `build_bundle_identity_dict`, `compute_bundle_fingerprint`, `verify_bundle_fingerprint`.

**Manifest audit:** `build_execute_prepared_manifest_commands` adds `bundle_fingerprint`, `apply_module`, and `governance_action_class` into the `audit` object inside `agent_execute_prepared_pipeline` so the governance digest binds to the same identity as the stored bundle.

**Execution check:** `execute_prepared_task_if_approved` compares the live `prepared_task` + `callback_selection` identity to `bundle_fingerprint_approved` on the bundle. **AWS + `ATP_GOVERNANCE_AGENT_ENFORCE`:** mismatch → **`governance.error=bundle_drift`**, execution skipped (ERROR log `governance_bundle_drift_detected`, `blocked=true`). When **`governance_tasks`** already has `gov-notion-<page_id>`, a **`governance_events`** `error` is also stored with **`signal_hint=drift`**. **Local / enforce off:** WARNING log, execution continues.

**Logs (structured JSON suffix):**

- `governance_bundle_fingerprint_created` — at bundle serialize (Telegram send path)
- `governance_bundle_fingerprint_verified` — fingerprint matched at execute
- `governance_bundle_drift_detected` — mismatch (`approved_fingerprint` vs `current_fingerprint`)

**Rollout note:** Execution manifests created **before** this change lack `bundle_fingerprint` in `audit`. The next execution rebuilds `expected_commands` with a fingerprint; digest will not match the approved manifest → treat as **invalidated** / blocked until a **new** approval request is sent (new manifest + digest).

### Adding a new apply callback safely

1. Return `governance_action_class` on the callback dict from `select_default_callbacks_for_task` (`GOVERNANCE_ACTION_CLASS_KEY` / `GOV_CLASS_*` constants).
2. Set **exactly one** of `ATP_GOVERNANCE_PROD_MUTATION_APPLY` or `ATP_GOVERNANCE_SAFE_LAB_APPLY` on the apply function (or on the OpenClaw closure in `_make_openclaw_callback`). Never set both.
3. Ensure the explicit class matches the marker/allowlist tier (e.g. do not set `patch_prep` on a function that is prod-marked).
4. If the callable is wrapped or re-exported, add `(module, __name__)` to the appropriate allowlist in `agent_execution_policy.py` — and keep it aligned with the explicit class.
5. Do **not** rely on free-text `selection_reason` alone on AWS.

If production logs show `governance_classification_conflict`, fix the callback pack so explicit class, markers, and allowlists agree; redeploy before expecting execution or Telegram approval to succeed under enforce.

**Reserved:** `EXECUTION_MODE_LAB_ONLY` in policy module for future explicit Notion-driven lab routing (not a bypass today).

## Path guard — wired write surfaces (LAB / OpenClaw)

| Module | Behavior |
|--------|----------|
| `agent_callbacks.py` | OpenClaw notes, sidecars, bug-investigation artifacts, verification feedback, `_write_if_missing` / preflight probes → `path_guard` |
| `cursor_handoff.py` | Handoff `.md` and README index under writable handoffs dir |
| `agent_recovery.py` | Regenerated investigation markdown |
| `agent_strategy_analysis.py`, `signal_performance_analysis.py`, `profile_setting_analysis.py` | `docs/analysis/**` and README index |
| `agent_versioning.py` | `docs/releases/CHANGELOG.md` append |
| `cursor_execution_bridge.py` | **`docs/agents/patches/{task_id}.diff`** via `path_guard`; staging writability probes remain raw (annotated `pg-audit-ignore`); git/cursor/pytest/npm use **list-argv** `subprocess.run([...])` in staging (no `shell=True`) |

**Subprocess / shell (review summary):** OpenClaw/LAB modules (`agent_callbacks`, `cursor_handoff`, `agent_recovery`, analyses, `openclaw_client`) do **not** use subprocess for file writes. `cursor_execution_bridge` uses subprocess for **staging** clone/CLI/tests only; repo `docs/` persistence from this module is **capture_diff** → `path_guard`. `scheduler.py` runs `watchlist_consistency_check.py` via `python script` (no shell redirection); that script writes reports with `path_guard` when under `docs/`. `governance_executor` subprocess = PROD/governed. **Audit** adds CI errors for `shell=True` / `os.system` / string subprocess / `create_subprocess_shell` **only** inside `LAB_ENFORCED` basenames.

**Scripts using path_guard for doc outputs:**

| Script | Output |
|--------|--------|
| `scripts/backfill_sections_json.py` | `.sections.json` under `docs/agents/*`, `docs/runbooks/triage` |
| `scripts/debug_btc_throttle_runtime.py` | `docs/monitoring/BTC_THROTTLE_STRESS_LOG.md` |
| `scripts/watchlist_consistency_check.py` | `docs/monitoring/*.md` when resolved under `docs/`; `/tmp/watchlist_consistency_reports` fallback stays unguarded (operational) |

**Intentionally not using path guard (PROD / separate concerns):**

| Module | Reason |
|--------|--------|
| `agent_strategy_patch.py` | Applies code changes; governed by approval + executor, not LAB doc policy |
| `cursor_execution_bridge.py` (staging) | Staging dirs under `ATP_STAGING_ROOT` / `/tmp` — not repo `docs/` artifacts |
| `notion_env.py`, `config_loader.py` | Runtime/env configuration writers |
| `task_fallback_store.py` | `backend/app/data/task_fallback.json` — operational queue, not LAB artifact |
| `agent_activity_log.py` | `logs/agent_activity.jsonl` — observability |
| `app/services/_paths.py` | Writable-dir probes; low-level path discovery (does not implement OpenClaw artifact policy) |

**Other services with direct writes (audit classifies as info/warn):** `signal_monitor.py`, `margin_leverage_cache.py`, `exchange_sync.py`, `crypto_com_trade.py`, `telegram_commands.py` (trigger file), `ai_engine/engine.py` (AI run JSON under configured run dir / tmp).

**Tests:** `backend/tests/test_path_guard.py`, `backend/tests/test_path_guard_audit.py`.

### Audit classification (representative)

| File / area | Typical write | Bucket | Action |
|-------------|---------------|--------|--------|
| `agent_callbacks.py` | `path_guard.safe_*` | LAB / guarded | Done |
| `cursor_execution_bridge.capture_diff` | `path_guard.safe_write_text` | LAB / guarded | Done |
| `cursor_execution_bridge` staging probe | `write_text` + `pg-audit-ignore` | Operational probe | Documented |
| `agent_strategy_patch.py` | `path.write_text` | PROD / governed | Exempt in audit; no path_guard |
| `config_loader.py`, `notion_env.py` | config / env | Operational / PROD | Exempt in audit |
| `task_fallback_store.py`, `agent_activity_log.py` | JSON / JSONL | Operational storage | Exempt |
| `backfill_sections_json.py` | sidecar JSON | LAB | Hardened with path_guard |
| `watchlist_consistency_check.py` | report `.md` | LAB when under `docs/` | Hardened; `/tmp` fallback raw |
| `ai_engine/engine.py` | doctor run JSON | Operational (not docs tree) | Exempt basename `engine.py` in audit |
| Shell / CI | redirection | Bypass | Not scanned by path_guard or static audit (no string parsing for `>` / `tee`) |
| `cursor_execution_bridge` | `subprocess.run(["git", ...])` | Staging / operational | Allowed; not a LAB `docs/` write path |
| LAB-enforced file | `shell=True` / `os.system` | Legacy / risky | Audit **error**; refactor to argv-only + `path_guard` for outputs |

## Remaining gaps (explicit)

- **Legacy `send_patch_deploy_approval`** (non–release-candidate format): still uses direct deploy path unless you standardize on release-candidate flow.
- **Other APIs** (workflows, control routes, scripts): not wrapped.
- **LAB vs PROD IAM**: still required at infrastructure layer.
- **Path guard**: raw writers in non-LAB modules; symlink-heavy `docs/` layouts; shell redirection hidden in variables or non-LAB files; scripts not yet using `path_guard` (see audit with `--include-scripts` for a fuller list). **Subprocess audit** does not inspect argv list contents for `>` / `tee`.

## Digest enforcement

1. On create, `digest = sha256(canonical_json({commands, scope_summary, risk_level}))`.
2. On every validity check, stored JSON is re-hashed; if it ≠ stored `digest`, status → `invalidated` and execution is denied.
3. On approve, any **other** `approved` manifest for the same `task_id` is set to `invalidated`.
4. Executor passes `expected_commands` parsed from the manifest row into `is_manifest_approved_and_valid` so the **live** command list must match the approved digest.

## Approval TTL (minutes)

| risk_level | TTL |
|------------|-----|
| low | 30 |
| medium | 20 |
| high | 10 |
| critical | 5 |

After TTL, status moves to `expired` on check.

## Enable / disable enforcement

| Variable | Default | Effect |
|----------|---------|--------|
| `ATP_GOVERNANCE_ENFORCE` | unset / false | Monitoring restart works; governance API still usable |
| `ATP_GOVERNANCE_ENFORCE=true` | — | On **AWS** (`ENVIRONMENT=aws`), unapproved monitoring restart is **blocked** |

Executor always requires approval regardless of this flag (the API is the controlled path).

## Rollout

1. Apply migration `20260322_create_governance_tables.sql` (or rely on boot-time `create_all` for governance tables when missing).
2. Set `GOVERNANCE_API_TOKEN` or reuse `OPENCLAW_API_TOKEN` for Bearer auth to `/api/governance/*`.
3. Exercise flows (see runbook); keep `ATP_GOVERNANCE_ENFORCE` off until restarts must go through manifests.
4. When ready on PROD, set `ATP_GOVERNANCE_ENFORCE=true` and `ENVIRONMENT=aws`.

## Whitelisted executor actions

- `noop` — tests / no-op
- `docker_compose_restart` — `profile` ∈ {`aws`,`local`}, `service` = `backend-aws`, `compose_relative` = `docker-compose.yml`
- `http_health` / `validate_http` — `http://127.0.0.1` or `localhost`, ports 8000 or 8002, path must include or equal `health`
- `agent_deploy_bundle` — `notion_task_id`; runs `apply_prepared_strategy_patch_after_approval` + `trigger_deploy_workflow` (intended for Telegram deploy approval when agent enforce is on)
- `agent_execute_prepared_pipeline` — `notion_task_id` + auditable `audit` block in manifest; runs `execute_prepared_task_if_approved` after digest validation (intended for agent task execution when agent enforce is on)

Extend the allowlists in `governance_executor.py` deliberately when new operations are needed.

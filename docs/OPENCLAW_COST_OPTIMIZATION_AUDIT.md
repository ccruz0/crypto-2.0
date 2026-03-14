# OpenClaw / ATP Cost Optimization Audit

**Date:** 2026-03-13  
**Scope:** OpenClaw integration, agent scheduler, backend LLM usage (OpenClaw gateway only).  
**Auth preserved:** OpenAI API on AWS; no ChatGPT subscription or browser/session auth.

---

## 1. Executive summary

**Verdict: Optimized now with these changes.**

The setup was already **partially optimized** (cheap-first model chain, single scheduler, no duplicate loops). Gaps addressed: (1) verification used the same (potentially expensive) chain as main tasks → **verification-specific model chain**; (2) token/usage telemetry → **usage extraction in openclaw_client** and **per-task cost log in agent_callbacks** (`openclaw_apply_cost`); (3) verification prompt length and verification-on/off → **configurable cap** and **documented env vars**. No duplicate schedulers, dead LLM paths, or unnecessary retries found. Operators can measure and tune cost via env vars and log aggregation without weakening reliability or observability.

---

## 2. Current cost drivers (audit findings)

### 2.1 Model call sites (all via `openclaw_client.send_to_openclaw`)

| Purpose | Location | Model chain | Frequency | Estimated tokens (order of magnitude) |
|--------|----------|-------------|-----------|---------------------------------------|
| **Apply** (investigation / doc / monitoring / generic) | `agent_callbacks._apply_via_openclaw` → `_call_openclaw_once` → `send_to_openclaw` | Main chain (`OPENCLAW_MODEL_CHAIN` or `OPENCLAW_PRIMARY_MODEL` + fallbacks) | 1 per task (+ up to 1 retry) | Input: 1k–8k (task + metadata + instructions); output: 0.5k–4k |
| **Verification** (PASS/FAIL review) | `openclaw_client.verify_solution_against_task` → `send_to_openclaw` | Same as main (before change) | 1 per task when `verify_solution_fn` is used and `ATP_SOLUTION_VERIFICATION_ENABLED` is true | Input: ~0.5k–2k (task + up to 8k chars of output); output: &lt;0.1k |

- **No other LLM call sites** in the backend: `agent_recovery` only parses existing content; `agent_anomaly_detector` does not call OpenClaw; `ai_engine` is scaffold-only (no model calls).

### 2.2 Background loops and polling

| Component | File | Interval / trigger | Calls OpenClaw? |
|-----------|------|--------------------|-----------------|
| Agent scheduler loop | `agent_scheduler.start_agent_scheduler_loop` | `AGENT_SCHEDULER_INTERVAL_SECONDS` (default 300s) | Indirect: 1 task per cycle → 1 apply (+ 1 verify if enabled) |
| Retry approved failed tasks | Same loop | Each cycle after main run | No extra OpenClaw; re-runs executor |
| Ready-for-patch continuation | Same loop | Each cycle | No extra apply; validation + optional verify |
| Recovery cycle | Same loop | Each cycle | No OpenClaw calls |
| Anomaly detection | Same loop | Each cycle | No OpenClaw calls |
| Buy index monitor | `buy_index_monitor` | 120s | No OpenClaw |
| Portfolio cache | `portfolio_cache` | 60s min | No OpenClaw |

- **Single scheduler loop**; no duplicate schedulers or dead OpenClaw call paths found.

### 2.3 Duplicated prompts, context, retries

- **Prompts:** Task-type-specific builders (investigation, documentation, monitoring, generic) share `_task_metadata_block` and `_STRUCTURED_OUTPUT_INSTRUCTION`. No duplicate full-context resend for the same task in one run.
- **Retries:** Apply has at most **1 retry** (2 attempts total) via `_OPENCLAW_MAX_RETRIES = 1` in `agent_callbacks.py`. Reasonable.
- **Verification:** One call per task when enabled; no retry loop. Verification prompt previously capped at 8000 chars; now configurable via `OPENCLAW_VERIFICATION_MAX_CHARS`.

### 2.4 What was already good

- **Cheap-first model chain** and failover (rate limit, 402, 5xx, timeout) in `openclaw_client.py`; doc: `docs/OPENCLAW_LOW_COST_MODEL_FALLBACK_STRATEGY.md`.
- **`OPENCLAW_CHEAP_FIRST_MODE=true`** by default.
- **Solution verification** can be turned off with `ATP_SOLUTION_VERIFICATION_ENABLED=false` (one fewer LLM call per task).
- **Single agent scheduler**; one task per cycle; no redundant polling.
- **Agent recovery** does not call OpenClaw (only parses existing investigation content).
- **Gateway** (OpenClaw container) already uses `OPENCLAW_MODEL_PRIMARY=openai/gpt-4o-mini` and fallbacks in docker/env.

---

## 3. What was changed

### 3.1 Verification model chain (`openclaw_client.py`)

- **`_verification_model_chain()`:** Reads `OPENCLAW_VERIFICATION_MODEL_CHAIN` (comma-separated) or `OPENCLAW_VERIFICATION_PRIMARY_MODEL` (single model). If set, verification uses this chain instead of the main chain; if unset, verification uses the main chain (unchanged behavior).
- **`verify_solution_against_task`** calls `send_to_openclaw(..., model_chain_override=verification_chain)` so verification can use a cheaper model (e.g. `openai/gpt-4o-mini` only) without changing main-task behavior.

**Rollback:** Unset `OPENCLAW_VERIFICATION_PRIMARY_MODEL` and `OPENCLAW_VERIFICATION_MODEL_CHAIN`; verification will again use the main chain.

### 3.2 Verification prompt length (`openclaw_client.py`)

- **`_verification_max_chars()`:** Reads `OPENCLAW_VERIFICATION_MAX_CHARS` (default 8000). Verification prompt sends only `generated_output[:max_chars]` to the model. Clamped to 500–50000.

**Rollback:** Set `OPENCLAW_VERIFICATION_MAX_CHARS=8000` or remove the env var.

### 3.3 Token/usage telemetry (`openclaw_client.py`)

- **`_extract_usage(data)`:** If the gateway response includes `usage` (e.g. `input_tokens`, `output_tokens`, `total_tokens`), it is extracted and attached to the result.
- **`_post_one`** returns `usage` in the result when present.
- **`send_to_openclaw`** logs `usage=...` in the success log line when the gateway provides it.

**Rollback:** Purely additive; if the gateway does not return `usage`, behavior is unchanged. No code revert needed for “no telemetry”.

### 3.4 Per-task cost logging (`agent_callbacks.py`)

- After a successful apply, when the OpenClaw result includes `usage` or `model_used`, the apply flow logs one line: `openclaw_apply_cost task_id=... model_used=... usage=...`. This allows log aggregation to attribute token/cost per task without changing behavior.

**Rollback:** Remove or comment out the `openclaw_apply_cost` log block in `_apply_via_openclaw` (agent_callbacks.py); no functional change, only one less log line.

### 3.5 Task-type model routing (`openclaw_client.py`, `agent_callbacks.py`)

- **`_cheap_task_types()`**, **`_cheap_task_model_chain()`**, **`get_apply_model_chain_override(prepared_task, save_subdir)`:** When `OPENCLAW_CHEAP_TASK_TYPES` and `OPENCLAW_CHEAP_MODEL_CHAIN` (or `OPENCLAW_CHEAP_PRIMARY_MODEL`) are set, doc/monitoring tasks use the cheap chain instead of the main chain. Bug investigations always use the main chain. Matching is by Notion task type (case-insensitive) or by save_subdir (generated-notes, triage).

**Rollback:** Unset `OPENCLAW_CHEAP_TASK_TYPES`, `OPENCLAW_CHEAP_MODEL_CHAIN`, and `OPENCLAW_CHEAP_PRIMARY_MODEL`; all tasks will use the main chain.

### 3.6 Config and docs

- **`.env.example`:** Documented `OPENCLAW_VERIFICATION_*`, `ATP_SOLUTION_VERIFICATION_ENABLED`, and task-type routing (`OPENCLAW_CHEAP_TASK_TYPES`, `OPENCLAW_CHEAP_MODEL_CHAIN`, `OPENCLAW_CHEAP_PRIMARY_MODEL`).
- **`secrets/runtime.env.example`:** Added commented examples for model chain, verification, and task-type routing for LAB/prod.

---

## 4. Expected cost impact

- **Verification on a cheaper model:** If verification was previously using the same chain as main (e.g. falling back to a stronger model), setting `OPENCLAW_VERIFICATION_PRIMARY_MODEL=openai/gpt-4o-mini` keeps verification on a single cheap model and avoids escalation for this small task. **Savings:** Depends on how often the main chain escalated; typically one cheaper call per task.
- **Verification prompt cap:** Reducing `OPENCLAW_VERIFICATION_MAX_CHARS` (e.g. to 4000) reduces input tokens for verification only. **Savings:** Modest per task; useful in cost-sensitive mode.
- **Disabling verification:** `ATP_SOLUTION_VERIFICATION_ENABLED=false` removes one LLM call per task. **Savings:** One full call per task; tradeoff is no automated PASS/FAIL review (see §5).
- **Task-type routing:** Setting `OPENCLAW_CHEAP_TASK_TYPES=doc,documentation,monitoring,triage` and `OPENCLAW_CHEAP_MODEL_CHAIN=openai/gpt-4o-mini` routes doc/monitoring tasks to a single cheap model. **Savings:** Per doc/monitoring task; bug tasks remain on full chain for quality.

---

## 5. Tradeoffs

- **Verification on a cheaper model:** Slight risk that a very weak model might mis-label PASS/FAIL. Mitigation: use a known-good cheap model (e.g. gpt-4o-mini); if quality drops, unset verification chain so verification uses the main chain again.
- **Lower `OPENCLAW_VERIFICATION_MAX_CHARS`:** Very long reports might be truncated before the “fix” section; reviewer might see less context. Mitigation: keep default 8000; reduce only when needed for cost.
- **`ATP_SOLUTION_VERIFICATION_ENABLED=false`:** No automated check that the output addresses the task. Human review or other QA should compensate.
- **Task-type routing:** A cheap model might produce lower-quality doc/monitoring output for complex tasks. Mitigation: unset `OPENCLAW_CHEAP_TASK_TYPES` to use main chain for all; or add a fallback model to the cheap chain.

---

## 6. New env vars and flags

| Variable | Default | Purpose |
|----------|---------|--------|
| `OPENCLAW_VERIFICATION_PRIMARY_MODEL` | (unset) | Single model for solution verification; if set, verification uses this instead of main chain. |
| `OPENCLAW_VERIFICATION_MODEL_CHAIN` | (unset) | Comma-separated verification chain; overrides `OPENCLAW_VERIFICATION_PRIMARY_MODEL` if both set. |
| `OPENCLAW_VERIFICATION_MAX_CHARS` | 8000 | Max characters of generated output sent to verification; clamped 500–50000. |
| `ATP_SOLUTION_VERIFICATION_ENABLED` | true | If false, solution verification step is skipped (one fewer LLM call per task). |
| `OPENCLAW_CHEAP_TASK_TYPES` | (unset) | Comma-separated task types that use the cheap chain (e.g. doc,documentation,monitoring,triage). Case-insensitive. |
| `OPENCLAW_CHEAP_MODEL_CHAIN` | (unset) | Comma-separated model chain for cheap task types; overrides `OPENCLAW_CHEAP_PRIMARY_MODEL` if both set. |
| `OPENCLAW_CHEAP_PRIMARY_MODEL` | (unset) | Single model for cheap task types when `OPENCLAW_CHEAP_MODEL_CHAIN` is unset. |

Existing: `OPENCLAW_MODEL_CHAIN`, `OPENCLAW_PRIMARY_MODEL`, `OPENCLAW_FALLBACK_MODEL_*`, `OPENCLAW_CHEAP_FIRST_MODE`, `OPENCLAW_API_URL`, `OPENCLAW_API_TOKEN`, `OPENCLAW_TIMEOUT_SECONDS`, `AGENT_SCHEDULER_INTERVAL_SECONDS`.

---

## 7. Diff-style summary of touched files

| File | Change |
|------|--------|
| `backend/app/services/openclaw_client.py` | Added `_verification_model_chain`, `_verification_max_chars`, `_extract_usage`; `_post_one` returns `usage` when present; `send_to_openclaw` accepts `model_chain_override`, logs usage on success; `verify_solution_against_task` uses verification chain and configurable max chars. |
| `backend/app/services/agent_callbacks.py` | After successful apply, log `openclaw_apply_cost` with task_id, model_used, and usage when present (per-task cost visibility). Task-type routing: call `get_apply_model_chain_override` and pass `model_chain_override` to `send_to_openclaw` for doc/monitoring tasks. |
| `backend/app/services/openclaw_client.py` | Added `_cheap_task_types`, `_cheap_task_model_chain`, `get_apply_model_chain_override` for task-type model routing. |
| `.env.example` | Documented `OPENCLAW_VERIFICATION_*` and `ATP_SOLUTION_VERIFICATION_ENABLED`. |
| `secrets/runtime.env.example` | Commented examples for OpenClaw model chain and verification. |
| `docs/OPENCLAW_COST_OPTIMIZATION_AUDIT.md` | Audit report and updates (this file). |

---

## 8. Verification checklist (no regression)

- [x] No existing core workflows broken: apply → validate → verify flow unchanged; verification is optional and chain override only affects which model is used.
- [x] System still starts and runs: no new required env vars; all new vars optional.
- [x] Config defaults sensible: verification uses main chain when new vars unset; max chars 8000 as before.
- [x] Fallback if cheaper model underperforms: unset verification chain to use main chain; or set verification chain to same as main.
- [x] No silent degradation in critical paths: verification still runs when `ATP_SOLUTION_VERIFICATION_ENABLED` is true; only the model selection and prompt length are configurable.

---

## 9. Tuning levers (no code change)

| Lever | Env / config | Effect |
|-------|----------------|--------|
| Scheduler frequency | `AGENT_SCHEDULER_INTERVAL_SECONDS` (default 300) | Higher value → fewer cycles → fewer task pickups and LLM calls; tradeoff: slower reaction to new Notion tasks. |
| Verification on/off | `ATP_SOLUTION_VERIFICATION_ENABLED=false` | Saves one LLM call per task; tradeoff: no automated PASS/FAIL review. |
| Verification model | `OPENCLAW_VERIFICATION_PRIMARY_MODEL` / `OPENCLAW_VERIFICATION_MODEL_CHAIN` | Use a single cheap model for verification. |
| Verification context size | `OPENCLAW_VERIFICATION_MAX_CHARS` (default 8000) | Lower value reduces verification input tokens. |
| Task-type routing | `OPENCLAW_CHEAP_TASK_TYPES` + `OPENCLAW_CHEAP_MODEL_CHAIN` (or `OPENCLAW_CHEAP_PRIMARY_MODEL`) | Doc/monitoring tasks use cheap chain; bug tasks always use main chain. |

## 10. Optional future improvements (not implemented)

- **Response caching:** Cache deterministic outputs (e.g. identical prompt → same result) is not implemented; would require cache key design and invalidation.

**Verify one full run:** Run `./scripts/run_notion_task_pickup.sh` (or `run_notion_task_pickup_via_ssm.sh`) and check logs for `openclaw_client: primary_model=...`, `openclaw_apply_cost task_id=... model_used=... usage=...`, and verification lines.

**Gateway usage verification:** If `openclaw_apply_cost` logs show `usage={}` or no usage, the OpenClaw gateway may not be returning `usage` (input_tokens, output_tokens, total_tokens) in its response. Add or fix usage in the gateway's `/v1/responses` response envelope so cost telemetry is populated. The backend already extracts and logs whatever the gateway provides.

**Task-type routing verification:** To confirm the cheap chain is used for doc/monitoring tasks, add a Planned task in Notion with Type = "doc" or "monitoring", then run `./scripts/run_notion_task_pickup.sh`. Check logs for `OpenClaw apply: using cheap chain for task ... save_subdir=...`. Bug tasks never use the cheap chain.

**Adding task-type vars to existing runtime.env:** Run `bash scripts/aws/append_openclaw_task_routing_to_runtime_env.sh` to append the vars to `secrets/runtime.env` without overwriting. Restart the backend afterward.

## 11. References

- `backend/app/services/openclaw_client.py` — model chain, failover, verification.
- `backend/app/services/agent_callbacks.py` — apply/validate/verify callbacks, retries, `openclaw_apply_cost` log.
- `backend/app/services/agent_scheduler.py` — single scheduler loop, intervals.
- `docs/OPENCLAW_LOW_COST_MODEL_FALLBACK_STRATEGY.md` — cheap-first and failover policy.

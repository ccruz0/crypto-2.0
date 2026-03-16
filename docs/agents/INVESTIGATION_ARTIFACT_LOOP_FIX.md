# Investigation Artifact Loop Fix

**Date:** 2026-03-16  
**Scope:** Task-runner / investigation-artifact loop for Notion AI Task System (Telegram / Notifications investigations)

---

## 1. Root Cause Summary

### A. Recovery path mismatch (primary)

**Problem:** Tasks routed to `telegram_alerts` or `execution_state` agents wrote artifacts to `docs/agents/telegram-alerts/` and `docs/agents/execution-state/`, but recovery only looked in `docs/agents/bug-investigations`, `docs/agents/generated-notes`, and `docs/runbooks/triage`.

**Effect:** Recovery never found the artifact, treated it as "missing", and reset the task to `planned`. The scheduler then re-picked the task, creating an infinite loop.

### B. Missing sections sidecar on fallback

**Problem:** When OpenClaw failed and `apply_bug_investigation_task` (template fallback) ran, it wrote only the `.md` file, not the `.sections.json` sidecar.

**Effect:** If the md was later lost or corrupted, recovery could not regenerate from the sidecar and reset the task.

### C. AGENT_OUTPUT_SECTIONS import failure

**Problem:** Some code paths imported `AGENT_OUTPUT_SECTIONS` from `openclaw_client` without defensive handling. If the import failed (e.g. circular import, deployment sync), the apply would fail with a cryptic error.

**Effect:** No fallback for telegram/execution agents when import failed; task stayed in-progress and retried indefinitely.

### D. Executor artifact check too narrow

**Problem:** The executor only checked `docs/agents/bug-investigations/notion-bug-{id}.md` when `expect_bug_artifact` was True. Telegram/execution agents used different paths and were skipped.

**Effect:** Task could advance to `investigation-complete` even when the artifact was missing (e.g. apply failed silently or wrote elsewhere).

---

## 2. Files Changed

| File | Change |
|------|--------|
| `backend/app/services/agent_recovery.py` | Added `telegram-alerts`, `execution-state` to `_ARTIFACT_CONFIGS`; added `artifact_exists_for_task()`; updated `_rebuild_markdown_from_sections` to support both INVESTIGATION_SECTIONS and AGENT_OUTPUT_SECTIONS schemas |
| `backend/app/services/agent_callbacks.py` | Defensive import for `AGENT_OUTPUT_SECTIONS` with fallback; added sidecar write to `apply_bug_investigation_task`; added `fallback_fn=apply_bug_investigation_task` for telegram_alerts and execution_state; defensive imports in `_validate_openclaw_note` |
| `backend/app/services/agent_task_executor.py` | Artifact check now uses `artifact_exists_for_task()` for all known paths; removed `expect_bug_artifact` parameter |
| `deploy_via_ssm.sh`, `deploy_aws.sh`, `deploy_all.sh`, `deploy_via_eice.sh` | Create `telegram-alerts` and `execution-state` dirs with correct ownership |

---

## 3. Patch Explanation

1. **Recovery paths:** `_ARTIFACT_CONFIGS` now includes `(docs/agents/telegram-alerts, notion-telegram)` and `(docs/agents/execution-state, notion-execution)`. Recovery finds artifacts written by multi-agent operators.

2. **Sidecar on fallback:** `apply_bug_investigation_task` writes `notion-bug-{id}.sections.json` with `{"_preamble": note_contents}` so recovery can regenerate if needed.

3. **Import resilience:** When `use_agent_schema=True` and `AGENT_OUTPUT_SECTIONS` import fails, we use `fallback_fn` (apply_bug_investigation_task) instead of failing. Validation uses local fallback tuples when import fails.

4. **Fallback for agents:** Telegram and Execution agents now have `fallback_fn=apply_bug_investigation_task`, so import/OpenClaw failures still produce an artifact.

5. **Executor artifact check:** Uses `artifact_exists_for_task()` which checks all artifact configs, ensuring we don't advance when the artifact is missing regardless of which callback wrote it.

6. **Regeneration schema:** `_rebuild_markdown_from_sections` supports both INVESTIGATION_SECTIONS and AGENT_OUTPUT_SECTIONS so recovery can regenerate from agent sidecars.

---

## 4. Safeguards Added

- **Deterministic import failures:** Use fallback when `AGENT_OUTPUT_SECTIONS` import fails; no endless retries.
- **Artifact + sidecar validation:** Executor advances only when `artifact_exists_for_task()` returns True (checks all paths).
- **Idempotent recovery:** Recovery still uses max 1 attempt per task; now finds artifacts in all agent paths.

---

## 5. Verification Performed

- `_get_artifact_paths` returns 5 configs including telegram-alerts and execution-state
- `artifact_exists_for_task` works
- No linter errors on changed files

---

## 6. Remaining Risks / Follow-ups

- **Deploy sync:** Ensure production has the updated code; the import error may have been from an older deployment.
- **Directory creation:** `docs/agents/telegram-alerts` and `docs/agents/execution-state` are created by the apply callback; ensure deploy scripts don't need to pre-create them.
- **Monitoring:** Add a metric or log when fallback is used due to import failure to surface deployment/config issues.

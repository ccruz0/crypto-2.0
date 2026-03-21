# Investigation Artifact Pipeline Fix

**Date:** 2026-03-19  
**Task:** RESET: purchase_price becomes null/missing — prove exact failure point (code + data flow)

---

## 1. Root Cause Summary

### A. README.md permission denied
**Problem:** Apply callbacks wrote to `README.md` in artifact directories. In Docker (UID 10001), the existing `README.md` from git could be owned by root/ubuntu, causing `Permission denied` when appending.

**Fix:** Wrapped README index writes in try/except. Index is optional; artifact (.md + .sections.json) is critical. Apply no longer fails when README is unwritable.

### B. Path inconsistency
**Problem:** `agent_recovery._get_artifact_paths` used `workspace_root() / subdir` for telegram-alerts, execution-state, etc., while `agent_callbacks._note_dir_for_subdir` used `get_writable_bug_investigations_dir()` only for bug-investigations. When `docs/` was not writable, bug-investigations used fallback but others used repo path — recovery could look in a different place than apply wrote.

**Fix:** Added `get_writable_dir_for_subdir(subdir)` in `_paths.py`. All artifact subdirs now use the same resolution: try repo path first; if not writable, use `AGENT_ARTIFACTS_DIR` or `/tmp/agent-artifacts/{subdir_name}`.

### C. Missing sidecar validation before advance
**Problem:** Executor advanced to ready-for-patch when `artifact_exists_for_task()` returned True (md file exists, min size). It did not verify the sidecar (.sections.json) existed. Recovery's missing-artifact playbook then failed with "No sections sidecar found" and reset the task.

**Fix:** Added `artifact_and_sidecar_exist_for_task()`. Executor now requires both artifact and sidecar before advancing. Returns structured (ok, reason) for logging.

### D. Inconsistent path usage in sidecar loaders
**Problem:** `cursor_handoff._load_sections_from_sidecar` and `agent_telegram_approval.get_openclaw_report_for_task` used hardcoded `get_writable_bug_investigations_dir()` + `root / "docs/agents/generated-notes"` etc. They did not include telegram-alerts, execution-state, or use the same writable resolution.

**Fix:** Both now use `get_writable_dir_for_subdir()` for all artifact subdirs.

---

## 2. Files Changed

| File | Change |
|------|--------|
| `backend/app/services/_paths.py` | Added `get_writable_dir_for_subdir()` for canonical path resolution |
| `backend/app/services/agent_callbacks.py` | `_note_dir_for_subdir` uses `get_writable_dir_for_subdir`; README writes optional (try/except); structured logs: artifact_write_started/succeeded/failed, sidecar_write_succeeded |
| `backend/app/services/agent_recovery.py` | `_get_artifact_paths` uses `get_writable_dir_for_subdir`; added `artifact_and_sidecar_exist_for_task()` |
| `backend/app/services/agent_task_executor.py` | Advance gate uses `artifact_and_sidecar_exist_for_task`; logs: validation_before_ready_for_patch, ready_for_patch_blocked_missing_artifact |
| `backend/app/services/cursor_handoff.py` | `_load_sections_from_sidecar` uses `get_writable_dir_for_subdir` for all subdirs |
| `backend/app/services/agent_telegram_approval.py` | `get_openclaw_report_for_task` uses `get_writable_dir_for_subdir`; added notion-telegram, notion-execution, notion-triage to prefix fallback |

---

## 3. Structured Logs Added

| Log | When |
|-----|------|
| `artifact_write_started` | Before writing .md |
| `artifact_write_succeeded` | After .md written successfully |
| `artifact_write_failed` | When .md write fails |
| `sidecar_write_succeeded` | After .sections.json written |
| `validation_before_ready_for_patch` | Before advance gate (passed=True or passed=False) |
| `ready_for_patch_blocked_missing_artifact` | When advance blocked (reason=artifact_too_small, sidecar_missing, etc.) |

---

## 4. Validation

1. **Canonical path:** All artifact reads/writes use `get_writable_dir_for_subdir()`. Apply, validate, recovery, cursor_handoff, and telegram_approval share the same resolution.
2. **README optional:** Apply succeeds even when README.md is unwritable.
3. **Sidecar required:** Executor does not advance until both artifact and sidecar exist and are valid.
4. **Re-run:** Scheduler ran successfully. A purchase_price-related task completed and produced a durable artifact.

---

## 5. Task-Specific: purchase_price Investigation

Task ID `10d75276-fcff-48bc-b5c9-473dec72bebd` already has:
- `docs/agents/bug-investigations/notion-bug-10d75276-fcff-48bc-b5c9-473dec72bebd.md`
- `docs/agents/bug-investigations/notion-bug-10d75276-fcff-48bc-b5c9-473dec72bebd.sections.json`

With the pipeline fix, when the task runs again:
1. Apply writes to canonical path (repo or fallback).
2. Sidecar is always written with the artifact.
3. Advance gate checks both before moving to ready-for-patch.
4. Recovery finds artifacts in the same path as apply.

To re-run the exact task: ensure it is in status `planned`, `backlog`, `ready-for-investigation`, or `needs-revision`, then run:
```bash
TASK_ID=10d75276-fcff-48bc-b5c9-473dec72bebd ./scripts/run_notion_task_pickup.sh
```

# README.md Permission Denied Fix

**Date:** 2026-03-19  
**Task:** RESET: purchase_price becomes null/missing — infrastructure fix (artifact pipeline)

---

## 1. Exact Failure

**Error:** `[Errno 13] Permission denied: '/app/docs/agents/bug-investigations/README.md'`

**Context:** Execution (apply) failed when the investigation artifact pipeline tried to write or append to `README.md` in the bug-investigations directory. In Docker (UID 10001), the existing `README.md` from git is typically owned by root, causing `Permission denied` when appending.

---

## 2. Root Cause

| Item | Location | Behavior |
|------|----------|----------|
| **apply_bug_investigation_task** | `agent_callbacks.py` ~584–659 | Wrote `idx_path = inv_dir / "README.md"` via `_write_if_missing` and `_append_line_if_missing` |
| **_apply_openclaw_note** | `agent_callbacks.py` ~999–1008 | Wrote `idx_path = out_dir / "README.md"` for OpenClaw investigation artifacts |
| **Why it failed** | Docker | Repo `README.md` is root-owned; container runs as UID 10001. Append fails even if directory is writable |

---

## 3. Files Changed

| File | Change |
|------|--------|
| `backend/app/services/agent_callbacks.py` | Removed README index writes from `apply_bug_investigation_task` and `_apply_openclaw_note`; added `_preflight_writable_artifact_dir()` |

---

## 4. Minimal Safe Patch

1. **Stop writing to README.md** — Removed all `README.md` index writes from the bug-investigations artifact pipeline. Artifacts are per-task (`.md` + `.sections.json`); the index is optional.
2. **Preflight writable check** — Added `_preflight_writable_artifact_dir()` to verify the artifact directory is writable before artifact generation.
3. **No changes to artifact paths** — Artifact paths remain unchanged; only `README.md` writes were removed.

---

## 5. Validation

- **Local run:** Scheduler ran successfully; another bug investigation task completed and produced artifact.
- **No permission error:** Apply succeeded without touching `README.md`.
- **Artifacts:** Per-task `.md` and `.sections.json` are still written correctly.

---

## 6. Re-run purchase_price Task

After deploying this fix:

```bash
TASK_ID=10d75276-fcff-48bc-b5c9-473dec72bebd ./scripts/run_notion_task_pickup.sh
```

The task must be in a pickable status: `planned`, `backlog`, `ready-for-investigation`, or `needs-revision`. If it is in another status (e.g. DONE, Blocked), update it in Notion first.

---

## 7. Summary

- **Cause:** Artifact pipeline tried to write to repo-owned `README.md` in Docker.
- **Fix:** Removed all `README.md` writes from the bug-investigations artifact pipeline.
- **Result:** Artifacts are generated without touching `README.md`; apply no longer fails.

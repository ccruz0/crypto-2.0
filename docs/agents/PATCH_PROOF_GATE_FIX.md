# Patch Proof Gate — Code Tasks Cannot Bypass Cursor Bridge

**Date:** 2026-03-19  
**Root cause:** Workflow allowed code-fix tasks to advance from investigation → ready-for-deploy without Cursor Bridge ever running. Deploy could happen with no code changes applied.

---

## 1. Root Cause in Workflow

**Bypass path:** In `advance_ready_for_patch_task`:

1. Cursor Bridge only ran when `CURSOR_BRIDGE_AUTO_IN_ADVANCE=true` (default: false)
2. When skipped, flow continued: validate_fn (checks **investigation artifact** markdown) → passes
3. record_test_result → advance to ready-for-deploy
4. send_patch_deploy_approval → [Approve Deploy] shown

**Problem:** Validation checked the investigation artifact (markdown), not code. Investigation is not implementation. No evidence of code changes was required.

---

## 2. Files / Functions Patched

| File | Change |
|------|--------|
| `backend/app/services/patch_proof.py` | **New module.** `is_code_fix_task`, `has_patch_proof`, `cursor_bridge_required_for_task` |
| `backend/app/services/agent_task_executor.py` | Patch proof gate before step 6; blocks advance when code-fix + handoff + no proof |
| `backend/app/services/agent_telegram_approval.py` | `send_patch_not_applied_message` — "Patch not yet applied" + [Run Cursor Bridge] |
| `backend/app/services/telegram_commands.py` | Deploy gate: block Approve Deploy for code tasks without patch proof |
| `backend/app/services/cursor_execution_bridge.py` | `cursor_bridge_started`, `cursor_bridge_succeeded`, `cursor_bridge_failed` logging |

---

## 3. Exact Gating Rule Added

**In `advance_ready_for_patch_task` (before record_test_result):**

```
IF cursor_bridge_required_for_task(task, task_id) returns (True, reason):
  → BLOCK advance to ready-for-deploy
  → Append Notion comment: "Validation passed but patch not yet applied..."
  → Send send_patch_not_applied_message (Telegram: "Patch not yet applied" + [Run Cursor Bridge])
  → Log deploy_blocked_no_patch
  → Return (stay in patching)
```

**In `_check_deploy_test_gate` / approve_deploy handler:**

```
IF code-fix task AND no patch proof:
  → Block deploy
  → Send "Patch not yet applied. Tap Run Cursor Bridge first."
  → Return (do not trigger deploy workflow)
```

---

## 4. Task Categories

| Category | Types | Cursor Bridge |
|----------|-------|---------------|
| **Code-fix** | bug, bugfix, investigation, architecture investigation | **Required** before deploy |
| **Doc/ops** | documentation, monitoring, triage, ops | May skip |

---

## 5. Patch Proof (Objective Evidence)

Any of:

- `docs/agents/patches/{task_id}.diff` exists and non-empty
- `cursor_patch_url` in Notion task metadata
- Activity log: `cursor_bridge_ingest_done`, `cursor_bridge_diff_captured`, or `cursor_bridge_auto_success` for this task

---

## 6. Structured Logging

| Event | When |
|-------|------|
| `cursor_bridge_required` | Code-fix task with handoff, no patch proof — blocking advance |
| `cursor_bridge_started` | run_bridge_phase2 begins |
| `cursor_bridge_succeeded` | Bridge completed, tests passed |
| `cursor_bridge_failed` | Bridge completed, tests or invoke failed |
| `cursor_bridge_skipped` | CURSOR_BRIDGE_AUTO_IN_ADVANCE not set |
| `deploy_blocked_no_patch` | Deploy blocked: code task has no patch proof |
| `deploy_allowed_with_patch` | Code task has patch proof; advance allowed |

---

## 7. purchase_price Task (10d75276-fcff-48bc-b5c9-473dec72bebd)

**Status:** No code change was applied. Task reached deploying without Cursor Bridge.

**To fix:**

1. In Notion: Set Status to **Patching** (or **Ready for Patch**)
2. In Telegram: Use **🛠️ Run Cursor Bridge** when it appears (or call `POST /api/agent/cursor-bridge/run` with `task_id`)
3. After bridge succeeds: deploy approval will be sent; then Approve Deploy

**Handoff:** No handoff exists for this task. Generate from investigation via `create_patch_task_from_investigation` (strict mode) or `generate_cursor_handoff` in cursor_handoff module. Then run Cursor Bridge.

---

## 8. Proof: Code Tasks Can No Longer Bypass

1. **advance_ready_for_patch_task:** Patch proof gate runs before record_test_result. Code-fix + handoff + no proof → block, send "Patch not yet applied", return.
2. **approve_deploy callback:** First checks `cursor_bridge_required_for_task`. If required and no proof → block, do not trigger deploy.
3. **Double gate:** Both scheduler path and Telegram approval path enforce the rule.

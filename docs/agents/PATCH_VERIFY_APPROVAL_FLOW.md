# PATCH → VERIFY → APPROVAL Automation Loop

This document describes the final automation loop: OpenClaw investigates → Cursor applies patch → system verifies → Telegram asks only for final deployment approval.

## Desired workflow

1. **Investigation** runs in OpenClaw (Notion task in `investigating` → `investigation-complete`).
2. If **strict proof** passes, a **PATCH task** is created (Notion; type=Patch or title `PATCH:`).
3. The **same** task is auto-advanced to **ready-for-patch**; scheduler picks it.
4. **Cursor path**: either human applies from handoff doc, or **Cursor bridge** runs (when `CURSOR_BRIDGE_AUTO_IN_ADVANCE=true`).
5. **Verification**: generic tests + task-specific `validate_fn` / `verify_solution_fn`.
6. If verification **passes** → task moves to **ready-for-deploy** → **one** Telegram approval message is sent.
7. If verification **fails** → no approval message; task stays in **patching** or moves to **needs-revision**; logs and status are clear.

## Gap that was addressed

- **Before:** The flow advanced to `awaiting-deploy-approval` and sent Telegram; there was no distinct “ready-for-deploy” state. The deploy approval message did not explicitly include root cause or “Do you want to deploy?”.
- **After:**
  - New state **ready-for-deploy**: patch + verification are done; **only** at this state we send the single Telegram approval.
  - Telegram message now includes: **task title**, **root cause**, **solution summary**, **files changed**, **verification result**, and the prompt **“Do you want to deploy?”** with [Approve Deploy] [Reject] [Smoke Check] [View Report].
  - No approval is sent during investigation or while in patching; approval is sent only when entering **ready-for-deploy**.

## New state transitions

- `patching` → **`ready-for-deploy`** (when validation + solution verification + test gate pass).
- `testing` → **`ready-for-deploy`** (same condition in the alternate path).
- **`ready-for-deploy`** → `deploying` (when user clicks **Approve Deploy** in Telegram).
- `deploying` → `done` (after deploy run / smoke check).

Backward compatibility: **awaiting-deploy-approval** is still supported (deploy gate and API accept both `ready-for-deploy` and `awaiting-deploy-approval`).

## How PATCH → VERIFY → APPROVAL works

1. **PATCH pickup**
   - Scheduler runs `continue_ready_for_patch_tasks()` every cycle.
   - It loads tasks with status **ready-for-patch** or **patching** via `get_tasks_by_status()`.
   - For each task it calls `advance_ready_for_patch_task(task_id)`.

2. **advance_ready_for_patch_task**
   - Moves task to **patching** if it was in ready-for-patch.
   - **Optional Cursor bridge:** if `CURSOR_BRIDGE_AUTO_IN_ADVANCE` is set and a handoff file exists, runs `run_bridge_phase2()` (apply + tests). If that passes, sets status to **ready-for-deploy**, sends **one** Telegram approval, returns.
   - Otherwise: re-selects callbacks to get `validate_fn` (and optionally `verify_solution_fn`).
   - Runs **validate_fn** (generic/task-specific validation). If it fails → task stays in **patching**, comment + log; no Telegram.
   - Runs **verify_solution_fn** if enabled (solution verification).
     - **Verification passed** → advance to ready-for-deploy, send deploy approval.
     - **Verification failed** (solution does not address task) → task moves to **needs-revision**, Telegram “Re-investigate”; no deploy approval.
     - **Verification unavailable** (OpenClaw not configured, API error, etc.) → advance to ready-for-deploy, send deploy approval with warning that verification was skipped; approval can proceed manually.
   - Calls **record_test_result** (test gate). On pass, **record_test_result** advances status to **ready-for-deploy**.
   - Then sends **send_patch_deploy_approval** (single Telegram message with root cause, solution, files, verification, “Do you want to deploy?”).

3. **Telegram**
   - Approval is sent **only** when the task has reached **ready-for-deploy** (or equivalent).
   - Buttons: [Approve Deploy] [Reject] [Smoke Check] [View Report].
   - **Approve Deploy** → deploy gate is checked (test status / status in `ready-for-deploy` or `awaiting-deploy-approval`) → status set to **deploying** → deploy workflow triggered.

## Files changed

| File | Change |
|------|--------|
| `backend/app/services/notion_tasks.py` | Added `TASK_STATUS_READY_FOR_DEPLOY`; `ALLOWED_TASK_STATUSES`; `EXTENDED_LIFECYCLE_TRANSITIONS`: patching/testing → ready-for-deploy, ready-for-deploy → deploying; Notion display map **Ready for Deploy**. |
| `backend/app/services/task_test_gate.py` | Advance to **ready-for-deploy** instead of awaiting-deploy-approval when tests pass. |
| `backend/app/services/agent_task_executor.py` | Bridge success path: set status to **ready-for-deploy** then send Telegram; validation path: comments and return value use **ready-for-deploy**; docstrings updated. |
| `backend/app/services/agent_telegram_approval.py` | `build_deploy_approval_message`: added **ROOT CAUSE**, **SOLUTION**, **VERIFICATION**; final line **“Do you want to deploy?”** and instruction to use Approve Deploy or Smoke Check. |
| `backend/app/services/telegram_commands.py` | Deploy gate: allow empty Test Status when status is **ready-for-deploy** or awaiting-deploy-approval; run_cursor_bridge success text says “ready-for-deploy”. |
| `backend/app/services/agent_recovery.py` | Doc and outcome check use **ready-for-deploy**. |
| `backend/app/services/cursor_execution_bridge.py` | Docstring: advance to **ready-for-deploy**. |
| `backend/app/services/notion_task_reader.py` | Fallback display map: **ready-for-deploy** → “Ready for Deploy”. |
| `backend/app/api/routes_agent.py` | Counts and active-tasks include **ready-for-deploy** (with Ready for Deploy). |

## Notion setup

Add **Ready for Deploy** as a Status select option in the AI Task System database so tasks can be set to this value by the backend.

## Manual verification steps

1. **PATCH pickup**
   - Create or use a task in **ready-for-patch** (or **patching**).
   - Run scheduler cycle (or wait for next run); confirm logs: `continue_ready_for_patch_tasks: advancing task_id=...` and `advance_ready_for_patch_task: ...`.

2. **Verification success**
   - With a task that has a valid `validate_fn` and passing validation: after one cycle the task should move to **ready-for-deploy** and one Telegram message should appear with task title, root cause, solution, files, verification, and “Do you want to deploy?”.

3. **Verification failure**
   - With a task that fails validation or solution verification: task should remain in **patching** or move to **needs-revision**; **no** deploy approval message.

4. **Deploy approval**
   - From the Telegram message, click **Approve Deploy**; task should move to **deploying** and deploy workflow should trigger (or show clear error).

5. **API**
   - `GET /api/agent/ops/status`: `tasks_awaiting_deploy` should include tasks in **ready-for-deploy** (and awaiting-deploy-approval).
   - `GET /api/agent/ops/active-tasks`: “awaiting” list should include tasks in **ready-for-deploy** and **Awaiting Deploy Approval**.

6. **Backward compatibility**
   - Tasks already in **awaiting-deploy-approval** should still pass the deploy gate and be deployable from Telegram.

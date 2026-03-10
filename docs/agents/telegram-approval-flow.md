# Telegram approval flow (agents)

This document describes how a human can **approve or deny** agent task execution from Telegram chat using inline buttons. It builds on the [human approval gate](human-approval-gate.md).

Implementation: `backend/app/services/agent_telegram_approval.py` and callback handling in `backend/app/services/telegram_commands.py`.

---

## Two approval flows

### Extended lifecycle (bug, strategy-patch, etc.) — 2 approvals

Tasks with `manual_only=True` (e.g. bug investigation, strategy-patch) use the **extended lifecycle**. The scheduler runs execution directly; no pre-execution approval is sent. The operator receives **two** approval messages:

1. **Investigation approval** — After OpenClaw analysis completes. Message includes: TASK, ROOT CAUSE, PROPOSED CHANGE, FILES AFFECTED, BENEFITS, RISKS, SCOPE, RISK CLASSIFICATION, ACTION REQUESTED. Buttons: **Approve**, **Reject**, **View Report**.
2. **Deploy approval** — After patch validation passes. Message includes: TASK, CHANGE SUMMARY, FILES CHANGED, TEST STATUS, BENEFITS, RISKS, SCOPE, RISK CLASSIFICATION, ACTION REQUESTED. Buttons: **Approve Deploy**, **Reject**, **Smoke Check**, **View Report**.

See [TELEGRAM_APPROVAL_UX_IMPROVEMENTS.md](TELEGRAM_APPROVAL_UX_IMPROVEMENTS.md) for details and examples.

### Legacy flow (non–manual_only) — 1 approval

Tasks that are not `manual_only` (e.g. documentation, monitoring triage that require approval) use the **legacy flow**:

1. **Send approval request** — Call `send_task_approval_request(prepared_bundle, chat_id=None)`. The module builds a Telegram message with TASK, PROPOSED CHANGE, FILES AFFECTED, BENEFITS, RISKS, SCOPE, RISK CLASSIFICATION, ACTION REQUESTED and sends it with **Approve**, **Deny**, **View Summary** buttons.

2. **User taps a button** — Only **authorized** Telegram users can use these buttons. Unauthorized users get "Not authorized".

3. **Approve** — When an authorized user taps **Approve**: the approval state is set to `approved`, execution runs via `execute_prepared_task_if_approved(bundle, approved=True)`, and a confirmation is sent.

4. **Deny** — When an authorized user taps **Deny**: the state is set to `denied`. No execution runs.

5. **View Summary** — Tapping **View Summary** resends the approval summary text. No state change.

6. **Inspecting a pending approval (detail view)**  
   From the **/agent** console, tap **Pending Approvals** to see the list. Each item has a **View** button. Tapping it opens a **detail view** for that request: task title, status, requested_at, project, type, priority, source, inferred repo area, callback reason, and full approval summary. From the detail view you can **Approve**, **Deny**, or **Back to Pending**. Approve/Deny use the same callback format as the original request message; behavior is unchanged.

---

## Callback button data format

Stable, short strings (Telegram `callback_data` is limited to 64 bytes):

### Legacy flow

- **Approve:** `agent_approve:<task_id>`
- **Deny:** `agent_deny:<task_id>`
- **View Summary:** `agent_summary:<task_id>`
- **Open detail (from pending list):** `agent_detail:<task_id>`
- **Back to pending list:** `agent_back_pending`
- **Execute approved task (from detail view):** `agent_execute:<task_id>`

### Extended lifecycle (investigation / deploy)

- **Approve patch:** `patch_approve:<task_id>`
- **Approve deploy:** `deploy_approve:<task_id>`
- **Reject:** `task_reject:<task_id>`
- **View report:** `view_report:<task_id>`
- **Smoke check:** `smoke_check:<task_id>`
- **Re-investigate:** `reinvestigate:<task_id>`

`task_id` is the Notion page ID (UUID) for the task.

---

## Authorized users

The same authorization as the rest of the Telegram bot applies:

- **Chat:** `TELEGRAM_CHAT_ID` (channel/group), or  
- **Users:** `TELEGRAM_AUTH_USER_ID` (comma/space-separated user IDs).

Only users/chats that pass `_is_authorized(chat_id, user_id)` in `telegram_commands.py` can approve or deny. Others see "Not authorized".

---

## Approval mechanism, not direct code edits

The Telegram flow is **only an approval mechanism**:

- It records a human decision (approve/deny) for a **prepared** task that already went through the approval gate.
- Execution is still done by the existing executor (`execute_prepared_task_if_approved`); the Telegram handler only sets the decision and triggers that call when the user taps Approve.
- No Telegram command directly edits code, runs shell, or deploys; all of that remains inside the callback-based executor.

---

## Persisted approval state (database)

Approval state is stored in the **database** (`agent_approval_states` table). The DB is the source of truth; an in-memory cache is used only for same-process fast path.

- **Table:** `agent_approval_states` (model: `backend/app/models/agent_approval_state.py`)
- **Fields:** `task_id`, `status` (pending | approved | denied), `requested_at`, `approved_by`, `decision_at`, `approval_summary`, `prepared_bundle_json`, **execution_status**, **execution_started_at**, **executed_at**, **execution_summary**
- **Behavior:**
  - Pending approvals **survive process restart**. Any process with DB access can read decisions and execute after approval.
  - `send_task_approval_request` writes a row (or updates existing) before sending Telegram; `record_approval` / `record_denial` update the row; `get_pending_approvals` and `get_task_approval_decision` read from DB first.
  - For execution, `load_prepared_bundle_for_execution(task_id)` reconstructs the bundle from `prepared_bundle_json` and re-runs callback selection (callables are not stored).
  - **Durable execution state** (see below) prevents duplicate execution and records whether execution was started, completed, or failed.

**Bundle reconstruction:** Callback functions cannot be serialized. Stored JSON contains `prepared_task`, `approval`, `approval_summary`, and `selection_reason`. On load, `select_default_callbacks_for_task(prepared_task)` is run again to reattach apply/validate/deploy callbacks. If callback selection rules change between request and execution, the selected callbacks may differ from the original request (same task metadata, so in practice they match).

**Durable execution state (duplicate execution prevention):** Each approval row has `execution_status` (`not_started` | `running` | `completed` | `failed`), `execution_started_at`, `executed_at`, and `execution_summary`. Before running execution, the flow calls `start_task_execution(task_id)`: it succeeds only when approval is `approved` and `execution_status` is not already `running` or `completed`. On success it sets `execution_status=running` and `execution_started_at=now`. After execution, `complete_task_execution` or `fail_task_execution` updates the row. So a second tap on **Execute Now** while status is `running` or after `completed` is blocked. **Retries are allowed** when `execution_status=failed`: the detail view shows **Retry Execute** and `can_execute_approved_task` returns true, so the user can run execution again.

---

## Detail view (inspect before approve/deny)

Authorized users can open a **detail view** for any pending approval from the **/agent** → **Pending Approvals** list by tapping **View** next to an item.

**Detail view fields:**

- Task title, status, requested_at
- **Execution:** execution_status, execution_started_at, executed_at (when set)
- approved_by, decision_at (when no longer pending)
- Project, type, priority, source
- Inferred repo area (area_name from stored prepared_task)
- Callback selection reason
- Full approval summary (truncated for Telegram length)

**Detail view buttons by status and execution state:**

- **pending:** Approve, Deny, Back to Pending
- **approved + execution_status not_started:** Execute Now, Back to Pending
- **approved + execution_status failed:** Retry Execute, Back to Pending
- **approved + execution_status running:** Back to Pending only
- **approved + execution_status completed:** Back to Pending only
- **denied:** Back to Pending only

**Actions:**

- **Approve** / **Deny** — Same as on the original approval message; callbacks `agent_approve:<task_id>` and `agent_deny:<task_id>`.
- **Execute Now** — Shown only when status is **approved**. Triggers execution via the existing flow; see [Execute Now (approved tasks)](#execute-now-approved-tasks) below.
- **Back to Pending** — Returns to the pending-approvals list (same message edited in place).

If the request is not found (e.g. already decided or expired), the bot shows a short "not found" message and a **Back to Pending** button.

---

## Execute Now (approved tasks)

When a task is already **approved**, the detail view shows an **Execute Now** button so an authorized user can trigger execution manually from Telegram.

**Pre-checks before execution:**

- **Authorization** — Same as for approve/deny; only authorized users can run Execute Now / Retry Execute.
- **Approval required first** — Execution is only allowed when approval status is `approved`. Pending or denied tasks cannot be executed from this button.
- **Execution state guard** — `can_execute_approved_task(task_id)` also checks durable execution state: if `execution_status` is `running` or `completed`, execution is not allowed (prevents duplicate runs). If `execution_status` is `failed`, execution **is** allowed (retry).
- **Bundle reconstruction** — The handler verifies the prepared bundle can be reconstructed from the DB. If any check fails, the bot shows a short "Cannot execute" message with the reason and **Back to Detail** / **Back to Pending** buttons.

**If checks pass:** The bot calls `start_task_execution(task_id)` (sets `execution_status=running`), then `execute_prepared_task_from_telegram_decision` runs the executor; on success `complete_task_execution` is called, on failure `fail_task_execution`. The result message shows execution state before attempt, whether execution was started, and final execution state after run.

---

## Related

- [Human approval gate](human-approval-gate.md) — When approval is required.
- [Task execution flow](task-execution-flow.md) — How execution runs after approval.
- Backend: `agent_telegram_approval.send_task_approval_request`, `get_task_approval_decision`, `get_approval_request_detail`, `can_execute_approved_task`, `get_task_execution_state`, `start_task_execution`, `complete_task_execution`, `fail_task_execution`, `execute_prepared_task_from_telegram_decision`; `telegram_commands._handle_agent_approval_callback`, `send_approval_request_detail`, `send_pending_agent_approvals`, `_format_execution_result_message`.

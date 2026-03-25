# Task execution flow (agents)

This document describes the canonical ATP execution flow for prepared Notion tasks.

Canonical lifecycle reference: `Telegram → planned → in-progress → investigation → investigation-complete → patch approval → patching → awaiting-deploy-approval → deploy approval → deploying → smoke → done/blocked`.

Implementation lives in `backend/app/services/agent_task_executor.py` and related scheduler/approval modules.

---

## Canonical status flow

| Phase | Primary function(s) | Status progression |
|-------|----------------------|--------------------|
| Intake | Telegram `/task` path | `planned` |
| Claim | `prepare_next_notion_task` | `planned → in-progress` |
| Investigation / artifact | callback `apply_change_fn` (often OpenClaw) | stays `in-progress` until investigation output is accepted |
| Investigation complete | executor/status update | `investigation-complete` |
| Patch approval | Telegram extended callback `patch_approve:*` | `investigation-complete → ready-for-patch` |
| Patch execution | `advance_ready_for_patch_task` / Cursor Bridge path | `ready-for-patch → patching → awaiting-deploy-approval` |
| Deploy approval | Telegram extended callback `deploy_approve:*` | `awaiting-deploy-approval → deploying` |
| Smoke gate / closure | `run_and_record_smoke_check` (webhook or Telegram trigger) | `deploying → done` or `deploying → blocked` |

---

## Execution model

Execution remains callback-injected (no hardcoded repo edits in the executor):

- `apply_change_fn(prepared_task)` — investigate/apply and produce artifacts
- `validate_fn(prepared_task)` — validation evidence used before deploy approval
- `deploy_fn(prepared_task)` — optional deployment callback path

The canonical operator-facing approvals are in the extended Telegram callback family (`patch_approve`, `deploy_approve`, `smoke_check`, `task_reject`, `reinvestigate`).

---

## Legacy note

Legacy lifecycle wording `in-progress → testing → deployed` still appears in some historical behavior and compatibility code paths, but it is not canonical documentation for ATP operations.

- `deployed` is a legacy terminal alias.
- Canonical successful terminal state is `done`.
- Canonical failure terminal state is `blocked`.

---

## Related

- [Task system](task-system.md) — Canonical lifecycle and status guidance
- [Notion task intake](notion-task-intake.md) — Intake, prioritization, and safe transitions
- [Telegram approval flow](telegram-approval-flow.md) — Canonical approval callbacks
- Backend: `backend/app/services/agent_task_executor.py`

# Telegram approval flow (agents)

This document describes the canonical Telegram approval flow for ATP tasks.

Implementation: `backend/app/services/telegram_commands.py` and `backend/app/services/agent_telegram_approval.py`.

---

## Canonical approval path

Canonical lifecycle stages that require operator action in Telegram:

1. **Patch approval** at `investigation-complete`
   - Callback: `patch_approve:<task_id>`
   - Status transition: `investigation-complete → ready-for-patch`

2. **Deploy approval** at `awaiting-deploy-approval`
   - Callback: `deploy_approve:<task_id>`
   - Status transition: `awaiting-deploy-approval → deploying`

3. **Smoke completion** (manual trigger when needed)
   - Callback: `smoke_check:<task_id>`
   - Status transition: `deploying → done` or `deploying → blocked`

Supporting callbacks in the same canonical family:
- `task_reject:<task_id>`
- `view_report:<task_id>`
- `reinvestigate:<task_id>`
- `run_cursor_bridge:<task_id>`

---

## Callback format (canonical)

- `patch_approve:<task_id>`
- `deploy_approve:<task_id>`
- `task_reject:<task_id>`
- `view_report:<task_id>`
- `smoke_check:<task_id>`
- `reinvestigate:<task_id>`
- `run_cursor_bridge:<task_id>`

`task_id` is the Notion page ID (UUID).

---

## Authorization

Only authorized Telegram users/chats can trigger approval callbacks, based on bot authorization checks in `telegram_commands.py`.

---

## Legacy note

The `agent_*` callback family is legacy:

- `agent_approve:<task_id>`
- `agent_deny:<task_id>`
- `agent_summary:<task_id>`
- related detail/execute helper callbacks

These remain in code for compatibility and older flows, but are not the canonical ATP approval path.

---

## Related

- [Task system](task-system.md)
- [Task execution flow](task-execution-flow.md)
- [Notion task intake](notion-task-intake.md)
- [Runbook: Notion to Cursor and deploy](../runbooks/NOTION_TASK_TO_CURSOR_AND_DEPLOY.md)

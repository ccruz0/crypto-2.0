# Telegram Approval Flow Redesign

## Root Cause of Approval Spam

### Previous Flow (Multiple Approval Gates)

1. **Legacy pre-execution approval** (`agent_scheduler.py`): For non-manual_only tasks with `approval_required=True`, sent `send_task_approval_request` before any investigation.

2. **Investigation-complete approval** (`agent_task_executor.py`): After OpenClaw analysis completes, sent `send_investigation_complete_approval` with [Approve] [Reject] [View Report] — human approval required to proceed to patch implementation.

3. **Deploy approval** (`agent_task_executor.py`, `advance_ready_for_patch_task`): After patch validation passes, sent `send_patch_deploy_approval` with [Approve Deploy] [Reject] [Smoke Check] [View Report].

### Why Duplication Occurred

- **No deduplication**: `send_investigation_complete_approval` and `send_patch_deploy_approval` did not track whether a message was already sent for a task.  
- **Scheduler cycle**: `advance_ready_for_patch_task` runs every 5 minutes for tasks in `ready-for-patch`; if validation passed but metadata persist failed, the task stayed in `patching` and the next cycle could re-send deploy approval.  
- **Early approval gate**: Investigation-complete was approval-gated before any patch existed; users approved "investigation only" repeatedly.

### Files Affected

| File | Functions |
|------|-----------|
| `backend/app/services/agent_telegram_approval.py` | `send_investigation_complete_approval`, `send_investigation_complete_info`, `send_patch_deploy_approval`, `build_investigation_approval_message`, `build_deploy_approval_message` |
| `backend/app/services/agent_task_executor.py` | `execute_prepared_notion_task` (extended lifecycle branch) |
| `backend/app/services/agent_scheduler.py` | `run_agent_scheduler_cycle`, `continue_ready_for_patch_tasks` |

---

## New Workflow

### Approval Model

- **Informational only** (no approval buttons):
  - Task detected
  - Investigation started
  - Investigation in progress
  - Root cause suspected
  - Recovery/retry happened
  - Artifact generated
  - Task reset
  - Investigation complete (INFO message)

- **Human approval required only for**:
  - Implementation-ready patch (awaiting-deploy-approval)
  - Sensitive infrastructure/config changes
  - Destructive or irreversible changes
  - Production-impacting actions

### Flow

```
planned → in-progress → investigating → investigation-complete
    → [INFO] send_investigation_complete_info (no buttons)
    → auto-advance to ready-for-patch
    → patching → validation
    → awaiting-deploy-approval
    → [APPROVAL REQUIRED] send_patch_deploy_approval (once, deduplicated)
    → user approves → deploying
```

### Message Type Prefixes

- `ℹ️ INFO` — Informational only
- `⚡ ACTION NEEDED` — User action required (no approval gate)
- `🔐 APPROVAL REQUIRED` — Human approval gate

---

## Changes Made

### 1. Investigation-complete → INFO only

- **Before**: `send_investigation_complete_approval` with [Approve] [Reject] [View Report]  
- **After**: `send_investigation_complete_info` with no approval buttons; message includes `ℹ️ INFO` prefix  
- **Auto-advance**: Task moves from `investigation-complete` to `ready-for-patch`; scheduler continues validation automatically

### 2. Deduplication for deploy approval

- In-memory cache: `_DEPLOY_APPROVAL_SENT[task_id] = timestamp`  
- Before sending, check `_DEPLOY_APPROVAL_DEDUP_HOURS` (24h); if already sent recently, skip  
- Prevents duplicate approval messages when `advance_ready_for_patch_task` runs every 5 minutes

### 3. Missing artifact handling

- If no OpenClaw report/artifact cached: send concise info message instead of approval request  
- Message: "No OpenClaw report/artifact cached. Approval deferred until valid report/artifact is available."  
- No approval buttons

### 4. Config: TELEGRAM_NOTIFICATION_MODE

- `minimal` (default): Fewer messages; investigation-complete has no View Report button  
- `verbose`: More status updates; investigation-complete includes [View Report] button  

### 5. Message prefixes

- Deploy approval: `🔐 APPROVAL REQUIRED — Patch ready to deploy`  
- Investigation info: `ℹ️ INFO — Investigation complete`

---

## Validation

- Investigation starts without asking approval.
- Status updates remain visible (INFO messages).
- Approval is requested only once when a real patch is ready (awaiting-deploy-approval).
- Duplicate approval prompts no longer occur (24h dedup).
- Legacy `send_investigation_complete_approval` remains for backward compatibility.
- Final human safety gate for deploy is preserved.

---

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `TELEGRAM_NOTIFICATION_MODE` | `minimal` | `minimal` = fewer messages; `verbose` = more status updates |

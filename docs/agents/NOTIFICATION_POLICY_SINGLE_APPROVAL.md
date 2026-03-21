# Notification Policy: Single Approval at Release-Candidate-Ready

This document describes the task and notification workflow where the user receives **exactly one approval request** at the end of the full implementation cycle.

## Required Behavior

- **Do not send approval requests** during investigation, patching, testing, verification, or intermediate iterations.
- OpenClaw iterates internally until either:
  1. All acceptance checks pass and a release candidate is ready, or
  2. A real blocker is reached.
- **Only when a release candidate is ready**, send one final approval message in Notion and Telegram.

## Final Approval Message Content

The single approval message must include:

- **Proposed version number** (example: atp.3.4)
- **Concise summary of problems solved**
- **Concise summary of improvements made**
- **Validation evidence** (tests, checks, runtime verification)
- **Known risks or open issues**
- **Clear approve/reject decision prompt**

## Allowed Messages Before Final Approval

- **Blocker notifications only**, and only for real blockers
- No approval-style prompts before release-candidate-ready
- Blocker messages are clearly marked as **BLOCKER** (not approval)

## State Machine

| State | Meaning |
|-------|---------|
| `investigating` | OpenClaw is analyzing the task |
| `patching` | Applying changes, running Cursor Bridge |
| `verifying` | Running validation and solution verification |
| `re-iterating` | Verification failed; needs revision → back to investigating |
| `release-candidate-ready` | All acceptance checks passed; **single approval trigger** |
| `approved` | User approved; task moves to deploying |
| `rejected` | User rejected |
| `blocked` | Real blocker reached; human intervention required |

## State Transitions

```
backlog → ready-for-investigation → investigating → investigation-complete
  → ready-for-patch → patching → release-candidate-ready
  → [APPROVAL] → deploying → done

patching → needs-revision (when verification fails)
needs-revision → investigating (when user approves re-investigate)
```

## Implementation Details

### Approval Trigger

- **Single trigger point:** `release-candidate-ready`
- `send_release_candidate_approval()` is called only when the task reaches `release-candidate-ready`
- `send_ready_for_patch_approval` and `send_investigation_complete_approval` are **disabled** (no-op, return skipped)
- No intermediate approval during patching or validation

### Idempotency (No Duplicate Approvals)

- **DB-backed dedup:** `TradingSettings` key `agent_release_candidate_approval:{task_id}:{proposed_version}`
- One approval per task + proposed_version; 7-day cooldown
- Survives process restarts and shared across workers
- Both main executor flow and Cursor Bridge success path use the same dedup

### Blocker Notifications

- `send_blocker_notification task_id, title, reason, suggested_action` sends a message with:
  - Prefix: `MSG_PREFIX_BLOCKER` — "🚫 BLOCKER"
  - Explicit text: "Real blocker (not an approval request)"
  - No approval buttons
- Use only for real blockers that require human intervention

### Deploy Gate

- Accepts `release-candidate-ready`, `ready-for-deploy`, and `awaiting-deploy-approval`
- Status `release-candidate-ready` is the canonical target after validation passes

## Notion Setup

Add **Release Candidate Ready** as a Status select option in the AI Task System database so tasks can be set to this value by the backend.

## Files

| File | Role |
|------|------|
| `backend/app/services/notion_tasks.py` | State constants, transitions, `TASK_STATUS_RELEASE_CANDIDATE_READY` |
| `backend/app/services/agent_telegram_approval.py` | `send_release_candidate_approval`, `send_blocker_notification`, `build_release_candidate_approval_message` |
| `backend/app/services/agent_task_executor.py` | Removed `send_ready_for_patch_approval`; calls `send_release_candidate_approval` in `advance_ready_for_patch_task` |
| `backend/app/services/task_test_gate.py` | Advances to `release-candidate-ready` (not `ready-for-deploy`) |
| `backend/app/services/telegram_commands.py` | Deploy gate accepts `release-candidate-ready` |

## Acceptance Criteria

- [x] User gets exactly one approval message for a successful work cycle
- [x] That message includes version, solved problems, improvements, and validation
- [x] Intermediate steps do not request approval
- [x] Blocker messages are still allowed, but clearly marked as blockers, not approvals

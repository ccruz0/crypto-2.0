# Telegram Approval UX Improvements

This document summarizes the changes made to reduce approval fatigue and improve the clarity of Telegram approval messages for the orchestration system.

## Summary of Changes

### 1. Reduced Approval Prompts

**Before:** Extended-lifecycle tasks (bug, strategy-patch, etc.) required **three** human approvals:
1. Legacy approval at scheduler (before any work)
2. Investigation-complete approval (after OpenClaw analysis)
3. Deploy approval (after tests pass)

**After:** Extended-lifecycle tasks require **two** approvals:
1. **Investigation approval** — after OpenClaw investigation completes
2. **Deploy approval** — after patch + tests pass, before deployment

The legacy pre-execution approval is skipped for `manual_only` tasks. The scheduler runs execution directly; the first human touchpoint is the investigation-complete message.

### 2. Exact Approval Points After Simplification

| Point | When | Message | Buttons |
|-------|------|---------|---------|
| **1. Investigation** | After OpenClaw analysis is saved and validated | `send_investigation_complete_approval` | Approve, Reject, View Report |
| **2. Deploy** | After patch validation passes, before deploy trigger | `send_patch_deploy_approval` | Approve Deploy, Reject, Smoke Check, View Report |

Legacy tasks (documentation, monitoring triage) that are not `manual_only` still use the original flow: one approval at scheduler if required, then full execution.

### 3. New Message Format

#### Investigation Approval Message

| Field | Source | Fallback |
|-------|--------|----------|
| TASK | Task title | `(no title)` |
| ROOT CAUSE | OpenClaw "Root Cause" section | `(not available)` |
| PROPOSED CHANGE | OpenClaw "Recommended Fix" section | `(not available)` |
| FILES AFFECTED | OpenClaw "Affected Files" section | `(not available)` |
| BENEFITS | Task Summary or "see proposed change" | `(see proposed change)` |
| RISKS | OpenClaw "Risk Level" | `Standard implementation risk ({risk} classification)` |
| SCOPE | `{n} file(s)` or "scope in report" | `(unknown)` |
| RISK CLASSIFICATION | Inferred from sections + task + area | LOW / MEDIUM / HIGH |
| ACTION REQUESTED | Fixed text | — |

#### Deploy Approval Message

| Field | Source | Fallback |
|-------|--------|----------|
| TASK | Task title | `(no title)` |
| CHANGE SUMMARY | Recommended Fix or Task Summary | `(not available)` |
| FILES CHANGED | Affected Files section | `(not available)` |
| TEST STATUS | Validation summary | `passed` |
| BENEFITS | Task Summary | `Addresses task requirements` |
| RISKS | Risk Level section | `Standard deploy risk ({risk} classification)` |
| SCOPE | `{n} file(s)` or "scope in report" | `(unknown)` |
| RISK CLASSIFICATION | Inferred | LOW / MEDIUM / HIGH |
| ACTION REQUESTED | Fixed text | — |

### 4. Risk Classification

Risk is inferred conservatively from:

1. **OpenClaw sections** — "Risk Level" section if present
2. **Task metadata** — type, project, details
3. **Repo area** — area_name, matched_rules
4. **Affected files** — deploy/execution logic (docker-compose, .yml, nginx, etc.) → HIGH

High-risk signals: deploy, docker, nginx, order, trade, exchange, signal, strategy, telegram_commands, crypto  
Medium-risk signals: monitor, health, sync, api, backend  
Default when uncertain: **MEDIUM**

### 5. Benefits / Risks / Scope Derivation

- **Benefits:** From Task Summary or Recommended Fix. If missing, use placeholder.
- **Risks:** From Risk Level section. If missing, use `Standard risk ({risk} classification)`.
- **Scope:** From Affected Files count (`{n} file(s)`), or "scope in report" if components present but no files, else `(unknown)`.

### 6. Example Messages

#### Example Investigation Approval

```
🔍 Investigation complete — approve implementation

TASK
Fix order sync delay in dashboard

ROOT CAUSE
Polling interval in exchange_sync.py is 60s; users see stale data for up to 1 minute.

PROPOSED CHANGE
Reduce interval from 60s to 30s in exchange_sync.py. Add config override via env var.

FILES AFFECTED
• backend/app/services/exchange_sync.py
• backend/app/core/config.py

BENEFITS
Faster order visibility; configurable for different environments.

RISKS
Slightly more API calls; may hit rate limits on high-volume exchanges.

SCOPE 2 file(s)

RISK CLASSIFICATION MEDIUM

ACTION REQUESTED
Approve to proceed with patch implementation, or Reject to stop.

[✅ Approve] [❌ Reject]
[📋 View Report]
```

#### Example Deploy Approval

```
🚀 Deploy approval

TASK
Fix order sync delay in dashboard

CHANGE SUMMARY
Reduce interval from 60s to 30s in exchange_sync.py. Add config override via env var.

FILES CHANGED
• backend/app/services/exchange_sync.py
• backend/app/core/config.py

TEST STATUS
✅ OpenClaw investigation validated (3 sections, 450 chars)

BENEFITS
Faster order visibility; configurable for different environments.

RISKS
Slightly more API calls; may hit rate limits on high-volume exchanges.

SCOPE 2 file(s)

RISK CLASSIFICATION MEDIUM

ACTION REQUESTED
Approve Deploy to trigger deployment, or Smoke Check first.

[🚀 Approve Deploy] [❌ Reject]
[🔍 Smoke Check] [📋 View Report]
```

## Affected Files

| File | Changes |
|------|---------|
| `backend/app/services/agent_scheduler.py` | Skip legacy approval for `manual_only` tasks; run execution directly |
| `backend/app/services/agent_telegram_approval.py` | Add `infer_risk_classification`, `build_investigation_approval_message`, `build_deploy_approval_message`; redesign `send_investigation_complete_approval`, `send_patch_deploy_approval`, and `send_task_approval_request` (legacy) with structured fields |
| `backend/app/services/agent_task_executor.py` | Pass `task` and `repo_area` to approval senders; fix indentation in deploy approval block |
| `docs/agents/telegram-approval-flow.md` | Document two approval flows (extended vs legacy); add extended callback button format |
| `docs/agents/human-approval-gate.md` | Add extended lifecycle section; update Telegram approval description |

## High-Risk Extra Approval

The system does not currently add extra approval gates for high-risk tasks. The risk classification is displayed in messages for operator awareness. To add an extra approval for clearly high-risk tasks (e.g. deploy/execution logic), you could:

1. Add `requires_extra_approval` to the approval decision in `agent_approval.py` when risk is HIGH and affected files touch deploy/execution.
2. In the scheduler, when `requires_extra_approval` is True, send the legacy approval before starting execution (reverting the skip for that subset).

This would be a small, localized change if needed.

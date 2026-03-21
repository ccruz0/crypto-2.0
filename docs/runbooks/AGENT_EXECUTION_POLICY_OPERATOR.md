# Agent Execution Policy — Operator Summary

## What Changed

The task execution flow now uses **safe autonomous mode** by default:

- **Investigation, diagnosis, patch prep, verification** → Run autonomously (no approval)
- **Production-affecting execution** → One approval at the end

## Approval Behavior

| Phase | Approval? |
|-------|-----------|
| Investigation | No |
| Patch preparation | No |
| Validation / verification | No |
| **Release candidate ready** | **Yes — single approval** |

## Strategy Patch (signal_monitor, etc.)

When `ATP_SAFE_AUTONOMOUS_MODE=true` (default):

1. Agent prepares patch proposal → writes to `docs/analysis/patches/notion-task-{id}.md`
2. **Does not** modify production files
3. When you tap **Approve Deploy** in Telegram:
   - Patch is applied to production files
   - Deploy workflow is triggered

## If You See "Prepared Only" in Patch Note

The patch note includes `## Prepared Only (Awaiting Approval): true` when the patch was not yet applied. After you approve deploy, it will be applied and the note updated to `false`.

## Rollback

- Reject from Telegram → task moves to rejected; no prod mutation
- If patch was applied and deploy failed: revert the changed files manually or via git

## Env Var

- `ATP_SAFE_AUTONOMOUS_MODE=true` (default) — prepare-only for strategy patch
- `ATP_SAFE_AUTONOMOUS_MODE=false` — legacy: patch applied during task run (before approval)

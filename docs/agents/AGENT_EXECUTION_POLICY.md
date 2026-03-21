# Agent Execution Policy: Safe Autonomous Mode

## Overview

The ATP task execution policy ensures:
- **Autonomous**: Investigation, diagnosis, patch preparation, and verification run without human interruption
- **One approval**: Only when a release candidate is ready for production-affecting execution
- **No prod mutation before approval**: Production code/config is not modified until the operator approves

## Action Classification

| Class | Description | Approval Required |
|-------|-------------|-------------------|
| **read_only** | Read docs, logs, configs, runtime state | No |
| **safe_ops** | Health checks, status snapshots, log inspection | No |
| **patch_prep** | Write to docs/, generate diffs, proposals | No |
| **prod_mutation** | Edit prod code/config, deploy, migrations, live behavior | **Yes** |

## Policy Module

`backend/app/services/agent_execution_policy.py`:

- `classify_callback_action()` — Classifies callback by `selection_reason`
- `requires_approval_before_apply()` — True for prod_mutation
- `is_safe_autonomous_mode()` — Reads `ATP_SAFE_AUTONOMOUS_MODE` (default: true)

## ATP_SAFE_AUTONOMOUS_MODE

When **true** (default):
- Strategy patch callback runs in **prepare-only** mode
- Writes patch proposal to `docs/analysis/patches/notion-task-{id}.md`
- Does **not** modify `signal_monitor.py` or other production files
- Approval triggers `apply_prepared_strategy_patch_after_approval()` which applies the patch, then deploy workflow

When **false** (legacy):
- Strategy patch applies directly to production files during the apply phase
- Same behavior as before this policy

## Task Lifecycle

```
backlog → ready-for-investigation → investigating → investigation-complete
  → ready-for-patch → patching → release-candidate-ready
  → [SINGLE APPROVAL] → deploying → done
```

- **No approval** during: investigation, patching, validation, verification
- **One approval** at: release-candidate-ready
- Approval payload includes: task title, root cause, files to change, actions, rollback plan, verification summary

## Callbacks by Class

| Callback | Class | Notes |
|----------|-------|------|
| Bug investigation (OpenClaw) | patch_prep | Writes to docs/agents/bug-investigations/ |
| Documentation | patch_prep | Writes to docs/ |
| Monitoring triage | patch_prep | Writes to docs/ |
| Strategy patch | prod_mutation | Edits signal_monitor.py — prepare-only when ATP_SAFE_AUTONOMOUS_MODE=true |
| Profile setting analysis | patch_prep | Analysis only, proposal to docs/ |
| Signal performance analysis | patch_prep | Analysis only |
| Strategy analysis | patch_prep | Analysis only |

## Deploy Approval Flow

1. Operator taps **Approve Deploy** in Telegram
2. Deploy gate checks: test status, patch proof (for code tasks)
3. `apply_prepared_strategy_patch_after_approval(task_id)` — applies any prepared strategy patch
4. `trigger_deploy_workflow()` — dispatches GitHub Actions

**Note**: If the deploy workflow deploys from `main`, the applied patch must be committed and pushed before the workflow runs. The backend applies the patch locally; for CI/CD deploy, the operator may need to commit and push the changes, or use a deploy path that includes the patch (e.g. Cursor Bridge PR merge).

## Environment Variables

| Variable | Default | Effect |
|----------|---------|--------|
| `ATP_SAFE_AUTONOMOUS_MODE` | `true` | Strategy patch: prepare-only (no prod mutation until approval) |

## Related

- [NOTIFICATION_POLICY_SINGLE_APPROVAL.md](NOTIFICATION_POLICY_SINGLE_APPROVAL.md)
- [PATCH_VERIFY_APPROVAL_FLOW.md](PATCH_VERIFY_APPROVAL_FLOW.md)

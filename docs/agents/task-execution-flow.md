# Task execution flow (agents)

This document describes the **controlled execution flow** for already-prepared Notion tasks: apply changes, move to testing, validate, optionally deploy, and update the task lifecycle to **deployed** only when validations (and optional deployment) succeed.

The flow is implemented in `backend/app/services/agent_task_executor.py` via `execute_prepared_notion_task()`. A **human approval gate** applies before execution: low-risk callbacks (documentation, monitoring triage) may run automatically; higher-risk or unknown callbacks require explicit approval. See [human-approval-gate.md](human-approval-gate.md).

---

## Preparation vs execution

| Phase | Purpose | When status changes |
|-------|---------|----------------------|
| **Preparation** (`prepare_next_notion_task`) | Select next task, infer repo area, build plan, claim task. | planned → in-progress |
| **Execution** (`execute_prepared_notion_task`) | Run apply/validate/deploy via injected functions, update Notion. | in-progress → testing → deployed (only if validation and optional deploy succeed) |

Preparation does not edit code or run tests. Execution runs **injected** callbacks (`apply_change_fn`, `validate_fn`, `deploy_fn`); the module does not hardcode repository edits, test commands, or deployment commands.

---

## When a task moves to testing

The task is moved from **in-progress** to **testing** only after:

1. `apply_change_fn(prepared_task)` has been run and reported **success**.

If the apply step is not provided, execution is skipped and the task remains in-progress. If the apply step fails, the task **stays in-progress**; a failure summary is appended to the Notion page and the function returns a structured failure result.

---

## Why deployed requires successful validation

**Deployed** means the change has been validated and (if a deploy step is used) deployed. To avoid marking tasks as deployed when checks have not been run:

- If **no `validate_fn`** is supplied, the task is **never** moved to deployed. It stays in **testing** and a Notion comment is added: *"Validation still required (no validate_fn supplied)."*
- If **`validate_fn`** runs and **fails**, the task stays in **testing** and is not marked deployed.
- Only when **validation succeeds** does the flow consider moving to **deployed** (and then only if an optional `deploy_fn` also succeeds when provided).

---

## Why failed validation or failed deploy leaves the task in testing

- **Validation failed:** The change is not considered verified; the task remains in **testing** and a comment is appended with the validation failure summary. The lifecycle does not advance to deployed.
- **Deploy failed (when `deploy_fn` is provided):** Even if validation passed, deployment is part of “done.” The task remains in **testing** and a comment is appended with the deployment failure summary. The task is not marked deployed.

Only when **validation succeeds** and **deploy either is not provided or succeeds** does the status move to **deployed** and a final summary comment is appended.

---

## Injected functions (no hardcoded edits)

Execution uses **dependency injection** so that callers can plug in their own logic:

- **`apply_change_fn(prepared_task)`** — Apply code or docs changes. Return a `bool` (success) or a `dict` with `"success"` and optional `"summary"`. Exceptions are caught and treated as failure.
- **`validate_fn(prepared_task)`** — Run tests, lint, or other checks. Same return convention. If not provided, the task is never marked deployed.
- **`deploy_fn(prepared_task)`** — Optional. Run only when validation has succeeded. Same return convention. If it fails, the task stays in testing.

The executor does **not** run shell commands, edit files, or call deployment scripts itself; it only invokes these callbacks and updates Notion status and comments based on their results.

---

## Return shape of `execute_prepared_notion_task()`

The function returns a single dict with:

- **`executed_at`** — UTC ISO timestamp.
- **`task_id`** — Notion page ID.
- **`task_title`** — Task title.
- **`apply`** — `{ "attempted", "success", "summary" }`.
- **`testing`** — `{ "status_updated" }` (true if status was moved to testing).
- **`validation`** — `{ "attempted", "success", "summary" }`.
- **`deployment`** — `{ "attempted", "success", "summary" }`.
- **`final_status`** — `"in-progress"` | `"testing"` | `"deployed"`.
- **`success`** — True only when the task reached **deployed** (validation passed and deploy passed if provided).

---

## Minimal usage example

```python
from app.services.agent_task_executor import prepare_task_with_approval_check, execute_prepared_task_if_approved

bundle = prepare_task_with_approval_check()
if not bundle or not bundle.get("prepared_task", {}).get("claim", {}).get("status_updated"):
    print("No task claimed.")
else:
    approval = bundle.get("approval", {})
    out = execute_prepared_task_if_approved(bundle, approved=not approval.get("required"))
    if out.get("execution_result"):
        print("Final status:", out["execution_result"].get("final_status"), "Success:", out["execution_result"].get("success"))
```

---

## Related

- [Task system](task-system.md) — Lifecycle and when to move states.
- [Task preparation flow](task-preparation-flow.md) — How tasks are selected and claimed.
- Backend: `backend/app/services/agent_task_executor.py` (`execute_prepared_notion_task`, `summarize_execution_result`, `summarize_validation_result`, `summarize_deployment_result`).

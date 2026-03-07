# Task System for Agents (AI-readable)

How agents should interpret and execute tasks: lifecycle, planning, validation, and where to find logs and monitoring.

---

## Task lifecycle

Tasks move through clear states. Use these when planning or reporting work:

| State | Meaning |
|-------|---------|
| **planned** | Task is defined and scoped; not yet started. |
| **in-progress** | Work has started; code or docs are being changed. |
| **testing** | Changes are done; running tests or manual verification. |
| **deployed** | Changes are merged and deployed to production (or explicitly not deployed with reason). |

Agents should:
- Set or report task state when starting, finishing, or deploying.
- Prefer small, reviewable changes; break large work into tasks that fit this lifecycle.

---

## Updating Notion task status (agents)

When a task is tracked in Notion (AI Task System DB), agents should update the Notion page status using the backend helper functions (non-throwing):

- `update_notion_task_status(page_id, status, append_comment=None) -> bool`
- `advance_notion_task_status(page_id, current_status) -> bool`

**Allowed statuses (current lifecycle):** `planned`, `in-progress`, `testing`, `deployed`.

### When to move a task

- **planned → in-progress**
  - When the agent commits to working on the task and is about to start investigating/planning in-repo.
  - Recommended: append a short comment describing intent and immediate next steps.

- **in-progress → testing**
  - After changes are implemented and you are starting validation (tests, lint, manual checks, runbook verification).

- **testing → deployed**
  - Only after validations pass and the change is merged + deployed (or explicitly deployed via runbook).
  - Do not mark `deployed` if validation is incomplete or deployment hasn’t happened.

### Minimal usage example

```python
from app.services.notion_tasks import update_notion_task_status

update_notion_task_status(
    page_id=task["id"],
    status="in-progress",
    append_comment="Starting investigation; will produce a plan before edits.",
)
```

---

## Task preparation (select → claim → plan)

Agents should use the minimal preparation flow before implementing changes:

- Select highest-priority planned task
- Infer likely repo area
- Create a short execution plan
- Move task to `in-progress`
- Append plan to Notion as a comment

See: [task-preparation-flow.md](task-preparation-flow.md) and `backend/app/services/agent_task_executor.py`.

---

## Task execution (apply → testing → validate → deployed)

After preparation, agents run the **controlled execution flow** with injected functions (no hardcoded edits in the executor):

- **Apply** — Run `apply_change_fn(prepared_task)`; on success, move task to **testing** and append execution summary.
- **Validate** — Run `validate_fn(prepared_task)` if provided. If not provided, the task stays in **testing** and is never marked **deployed**.
- **Deploy** — Optionally run `deploy_fn(prepared_task)` only after validation succeeds.
- **Deployed** — Move to **deployed** only when validation (and optional deploy) succeed. Failed validation or failed deploy leaves the task in **testing**.

See: [task-execution-flow.md](task-execution-flow.md) and `execute_prepared_notion_task()` in `backend/app/services/agent_task_executor.py`.

---

## Version traceability (proposal → approval → release)

For business-logic improvements, the workflow also tracks version metadata:

- `current_version`
- `proposed_version`
- `released_version`
- `version_status` (`proposed`, `approved`, `released`, `rejected`)
- `change_summary`

At proposal time, the agent should also include:

- `affected_files`
- `validation_plan`

Version bump guidance:

- **patch**: small tuning changes
- **minor**: meaningful business-logic improvements
- **major**: architecture or core-strategy changes

See: [versioning-flow.md](versioning-flow.md).

---

## How agents should plan work

1. **Understand** — Read [system map](../architecture/system-map.md) and [context](context.md); identify affected components and [critical modules](context.md#critical-modules---do-not-break).
2. **Scope** — One clear objective per task (e.g. “add field X to endpoint Y”, “fix runbook Z”). If the user request is large, split into steps and treat each as a task.
3. **Check decisions** — Look at [decision-log](../decision-log/README.md) so you don’t propose something already decided against.
4. **Identify docs** — Which runbooks, architecture docs, or configs must be updated if behavior or procedures change.
5. **Dependencies** — Note order (e.g. backend change before frontend; schema before API).

---

## How changes should be validated

1. **Code**
   - Run backend tests: `cd backend && pytest` (or project’s test command).
   - Run frontend lint/tests if frontend is touched: e.g. `cd frontend && npm run lint` (or test script).
   - Pre-commit: repo uses pre-commit; run `pre-commit run --all-files` when relevant.

2. **Deploy and operations**
   - Follow [Deploy runbook](../runbooks/deploy.md) for production deploy.
   - After deploy: [POST_DEPLOY_VERIFICATION](../aws/POST_DEPLOY_VERIFICATION.md) or at least `curl` to `/api/health` and check dashboard loads.
   - Restarts: [Restart services](../runbooks/restart-services.md); verify with `docker compose --profile aws ps` and health checks.

3. **Documentation**
   - Links in new or edited docs must point to existing paths (architecture, runbooks, infrastructure, integrations, operations).
   - If you add a procedure, add or update a runbook and link from [RUNBOOK_INDEX](../aws/RUNBOOK_INDEX.md) or [docs/README](../README.md) when appropriate.

---

## Where logs and monitoring are

| What | Where |
|------|--------|
| **Backend logs** | On EC2: `docker compose --profile aws logs -n 200 backend-aws` (or follow with `-f`). |
| **Frontend logs** | On EC2: `docker compose --profile aws logs -n 200 frontend-aws`. |
| **Health check** | `GET /api/health` (e.g. `https://dashboard.hilovivo.com/api/health`). |
| **Dashboard diagnostic** | From repo: `bash scripts/debug_dashboard_remote.sh` (see [operations/monitoring](../operations/monitoring.md)). |
| **Runbooks** | [docs/runbooks/](../runbooks/), [docs/aws/RUNBOOK_INDEX.md](../aws/RUNBOOK_INDEX.md). |
| **Monitoring UI** | In-app monitoring tab (backend: `/api/monitoring/summary`, `/api/monitoring/telegram-messages`). |

When a task involves “check status” or “debug production”, start with health endpoint and runbooks; then container logs and diagnostic script.

---

## Summary for agents

- **Lifecycle**: planned → in-progress → testing → deployed.
- **Plan**: Read system map and context; scope one objective; check decision log; update docs if behavior or procedures change.
- **Validate**: Tests, lint, deploy runbook, post-deploy check; update runbooks when adding procedures.
- **Observe**: Backend/frontend logs on EC2; `/api/health`; dashboard diagnostic script; runbooks and monitoring docs.

# Task System for Agents (AI-readable)

How agents should interpret and execute tasks: lifecycle, planning, validation, and where to find logs and monitoring.

---

## Task lifecycle (canonical)

The canonical ATP lifecycle is:

`Telegram intake → planned → in-progress → investigation/artifact → investigation-complete → patch approval → patching → awaiting-deploy-approval → deploy approval → deploying → smoke check → done/blocked`

Use these statuses when planning, reporting, and operating tasks:

| State | Meaning |
|-------|---------|
| **planned** | Task is created and queued in Notion. |
| **in-progress** | Task has been claimed and investigation/implementation started. |
| **investigation-complete** | Investigation/artifact is complete and waiting for patch approval. |
| **ready-for-patch** | Human patch approval granted; task can enter patching flow. |
| **patching** | Patch is being applied/validated (Cursor Bridge or equivalent flow). |
| **awaiting-deploy-approval** | Patch/testing phase completed; waiting for deploy approval. |
| **deploying** | Deployment has been approved and triggered. |
| **done** | Deploy + smoke check succeeded; task closed successfully. |
| **blocked** | Task cannot progress (including failed smoke check). |

Legacy aliases still exist in code and old tasks, but are not canonical:
- `deployed` is a legacy terminal alias (use `done` for canonical closure).
- `agent_*` Telegram approval callbacks are legacy approval flow.

Agents should:
- Set or report task state when starting, finishing, or deploying.
- Prefer small, reviewable changes; break large work into tasks that fit this lifecycle.

---

## Updating Notion task status (agents)

When a task is tracked in Notion (AI Task System DB), agents should update the Notion page status using the backend helper functions (non-throwing):

- `update_notion_task_status(page_id, status, append_comment=None) -> bool`
- `advance_notion_task_status(page_id, current_status) -> bool`

**Canonical statuses for operations:** `planned`, `in-progress`, `investigation-complete`, `ready-for-patch`, `patching`, `awaiting-deploy-approval`, `deploying`, `done`, `blocked`.

**Legacy statuses (still present for compatibility):** `testing`, `deployed`, and older intermediate aliases.

### When to move a task

- **planned → in-progress**
  - Scheduler/executor claims task and starts investigation.

- **in-progress → investigation-complete**
  - Investigation/artifact produced and ready for human patch decision.

- **investigation-complete → ready-for-patch**
  - Human patch approval received (Telegram extended approval flow).

- **ready-for-patch → patching → awaiting-deploy-approval**
  - Patch execution/validation pipeline runs and reaches deploy gate.

- **awaiting-deploy-approval → deploying**
  - Human deploy approval received (Telegram extended approval flow).

- **deploying → done / blocked**
  - Smoke check determines final terminal state.

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

## Task execution (canonical path)

After preparation, agents run the controlled execution flow with injected functions:

- **Apply / investigate** — Run `apply_change_fn(prepared_task)` and produce investigation or patch artifacts.
- **Patch gate** — Human patch approval moves task to `ready-for-patch`.
- **Patch execution** — Move through `patching` to `awaiting-deploy-approval`.
- **Deploy gate** — Human deploy approval moves task to `deploying`.
- **Smoke gate** — Smoke check sets terminal state to `done` or `blocked`.

Legacy behavior (`testing` → `deployed`) remains for compatibility but is not canonical for new operational flow.

See: [task-execution-flow.md](task-execution-flow.md) and `execute_prepared_notion_task()` in `backend/app/services/agent_task_executor.py`.

---

## Execution mode

Tasks support an optional `execution_mode` property (Notion: "Execution Mode"):

| Value | Behavior |
|-------|----------|
| **normal** | Default. Standard flow; auto-advance to ready-for-patch after investigation. |
| **strict** | Blocks ready-for-patch until proof criteria are met: exact file, function, line/condition, code snippet, failing scenario, root cause, fix rationale. |

When `execution_mode=strict`, OpenClaw prepends a hard investigation override to the prompt and does not auto-advance unless the output passes validation. The task stays in-progress until proof is present.

### Manual verification (strict mode end-to-end)

1. Add **Execution Mode** Select property to the Notion AI Task System (options: Normal, Strict).
2. Create a bug investigation task and set Execution Mode = **Strict**.
3. Let the scheduler pick it up and run OpenClaw.
4. If the investigation output is shallow (no file path, function, code block, failing scenario, root cause, fix rationale), the task stays **in-progress** with a Notion comment explaining why.
5. Re-run (or wait for next cycle) after improving the task instructions or letting OpenClaw produce a deeper investigation.
6. When the output meets proof criteria, the task advances to investigation-complete → ready-for-patch as usual.

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

- **Canonical lifecycle**: Telegram intake → planned → in-progress → investigation/artifact → investigation-complete → patch approval → patching → awaiting-deploy-approval → deploy approval → deploying → smoke → done/blocked.
- **Plan**: Read system map and context; scope one objective; check decision log; update docs if behavior or procedures change.
- **Validate**: Tests, lint, deploy runbook, post-deploy check; update runbooks when adding procedures.
- **Observe**: Backend/frontend logs on EC2; `/api/health`; dashboard diagnostic script; runbooks and monitoring docs.

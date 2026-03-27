# Notion task → Cursor connection → new code deployment (full flow)

**When to use:** You want to run **any Notion task** from the AI Task System all the way to Cursor (apply code), validation, deploy approval, deployment, and task closure (done).

This runbook is the **canonical ATP lifecycle** reference.

Canonical flow:
`Telegram intake → Notion planned → claim in-progress → investigation/artifact → investigation-complete → patch approval → patching → awaiting-deploy-approval → deploy approval → deploying → smoke → done/blocked`

---

## Flow overview (canonical)

| Stage | Status(es) | Who / What |
|-------|------------|-------------|
| 0. Intake | Telegram `/task` → `planned` | Telegram + backend direct Notion create |
| 1. Pick & claim | `planned` → `in-progress` | Backend scheduler or manual (Notion + API) |
| 2. Investigate / prepare | `in-progress` | OpenClaw or you: analysis, triage, plan |
| 3. Investigation complete | → `investigation-complete` | Backend after apply step; sends patch approval |
| 4. Patch approved | → `ready-for-patch` | You approve in Telegram (extended callback flow) |
| 5. Cursor handoff | — | Backend writes `docs/agents/cursor-handoffs/cursor-handoff-{task_id}.md` |
| 6. Patch execution | `ready-for-patch` → `patching` → `awaiting-deploy-approval` | Telegram **"🛠️ Run Cursor Bridge"** or **POST /api/agent/cursor-bridge/run** |
| 7. Deploy approved | → `deploying` | You approve deploy in Telegram (extended callback flow) |
| 8. Deploy | — | Backend triggers GitHub Actions deploy workflow (governed or legacy dispatch path) |
| 9. Smoke check | `deploying` → `done` or `blocked` | GitHub webhook or Telegram **Smoke Check** button |

### Legacy notes

- `agent_approve:*` / `agent_deny:*` / `agent_summary:*` callback family is legacy and not the canonical approval path.
- `deployed` is a legacy terminal alias; canonical terminal success state is `done`.
- Older docs that mention `in-progress → testing → deployed` should be treated as compatibility behavior, not the primary operational flow.

---

## Create a new task and review the full flow

Use this when you want to **create a new Notion task from scratch** and walk the entire flow so you can review every stage.

### 0. Create the task in Notion

In your **AI Task System** database in Notion, create a **new page** with these properties (names must match exactly; backend reads **Task**, **Type**, **Status**, **Project**, **Details**):

| Property | Value | Why |
|----------|--------|-----|
| **Task** (or **Name** / **Task Title**) | `E2E flow test: add runbook link to README` | Short, clear title. |
| **Type** | `bug` | Ensures extended lifecycle (investigation → patch approval → Cursor Bridge → deploy). Use exactly `bug` (or `bugfix` / `bug fix`). |
| **Status** | `Planned` or `planned` | Scheduler only picks tasks with Status = planned. |
| **Project** | `Automation` or `Docs` | Optional; helps filtering. |
| **Details** (or **Description**) | `Add a single line to the repo README linking to docs/runbooks/NOTION_TASK_TO_CURSOR_AND_DEPLOY.md. No code logic changes. Purpose: exercise the full Notion → Cursor → deploy flow for review.` | Gives OpenClaw/fallback enough context to build a small, safe handoff. |

**Optional:** Set **Priority** to `medium` or `high` so it’s picked soon. Leave **Source** empty or set to `openclaw`.

After saving, copy the **page ID** (from the page URL: the 32-char hex after the workspace and optional `?v=`, or use Share → Copy link and take the last segment). You’ll need it for the Cursor Bridge API and to find the handoff file (`cursor-handoff-{page_id}.md`).

### Full-flow review checklist

Work through these in order and tick as you verify each step.

| # | Step | What to do | What to verify |
|---|------|------------|----------------|
| 1 | **Task created** | Create the Notion task as above; copy page ID. | Task appears in AI Task System with Status = Planned, Type = bug. |
| 2 | **Scheduler picks task** | Wait for the next scheduler cycle (or trigger if you have an API). Backend runs preparation + apply (investigation). | In Notion: Status → **in-progress**, then → **investigation-complete**. In Telegram: approval card for “Approve patch” / “Reject”. New files under `docs/agents/bug-investigations/` or `docs/runbooks/triage/` (and/or OpenClaw report). |
| 3 | **Cursor handoff exists** | — | File exists: `docs/agents/cursor-handoffs/cursor-handoff-{page_id}.md`. Open it and confirm it describes the task and expected outcome. |
| 4 | **Patch approved** | In Telegram, tap **Approve** on the investigation approval. | Notion: Status → **ready-for-patch**. Telegram may show **“🛠️ Run Cursor Bridge”**. |
| 5 | **Run Cursor Bridge** | Telegram: tap **“🛠️ Run Cursor Bridge”** — or call `POST /api/agent/cursor-bridge/run` with `{"task_id": "<page_id>"}`. | Bridge runs (staging, Cursor CLI, diff, tests). Notion: Status → **patching** → **awaiting-deploy-approval**. Telegram: deploy approval card. Optional: `docs/agents/patches/{page_id}.diff` and Test Status updated. |
| 6 | **Deploy approved** | In Telegram, tap **Approve** on the deploy approval. | Notion: Status → **deploying**. Backend triggers GitHub Actions deploy workflow. |
| 7 | **Deploy runs** | — | GitHub Actions: deploy workflow run completes (e.g. `deploy_session_manager.yml`). |
| 8 | **Smoke check → done** | Telegram: tap **Smoke Check** on the task’s card (or wait for GitHub webhook if configured). | Notion: Status → **done** (or **blocked** if smoke failed). Task is closed. |

If any step fails, use [PRODUCTION_ORCHESTRATION_DEBUGGING_GUIDE.md](PRODUCTION_ORCHESTRATION_DEBUGGING_GUIDE.md) and the **Troubleshooting** section below.

### Alternative new-task ideas (same flow)

- **Doc-only:** “Add a ‘See NOTION_TASK_TO_CURSOR_AND_DEPLOY.md’ line to docs/README.md.”
- **Trivial code:** “In backend README or a single comment, add a one-line reference to this runbook.”
- **Monitoring-style:** Use **Type** = `monitoring` and a title like “Triage: verify health endpoint returns 200” to get the monitoring-triage flow (triage note + handoff); then same Cursor Bridge → deploy → smoke path.

---

## Prerequisites

- **Notion:** AI Task System database with `NOTION_API_KEY` and `NOTION_TASK_DB` set on the backend.
- **Backend:** Agent scheduler running (picks up `planned` tasks); optional: `CURSOR_BRIDGE_ENABLED=true` for Cursor Bridge.
- **Telegram:** Approval bot configured so you can approve **investigation** → **patch** → **deploy** and run **Run Cursor Bridge** / **Smoke Check**.
- **Cursor Bridge (for code apply):** Cursor CLI in PATH on the host that runs the backend (or `CURSOR_CLI_PATH`), `ATP_STAGING_ROOT` writable; handoff file exists for the task.
- **Deploy:** `GITHUB_TOKEN` with `actions:write` (and repo access) for `trigger_deploy_workflow`; GitHub Actions deploy workflow (e.g. `deploy_session_manager.yml`) and optional webhook for post-deploy smoke.

---

## Step-by-step (extended lifecycle)

### 1. Ensure a task exists and is planned

- In Notion, create or pick a task in the AI Task System DB with **Status** = **Planned** (and **Type** e.g. `bug` or `monitoring` so the backend selects the extended-lifecycle callbacks).
- Backend scheduler will pick it up (or you can trigger preparation via API if your setup supports it).

### 2. Let the backend prepare and run investigation

- Scheduler runs periodically: it reads pending tasks, selects one, claims it (`planned` → `in-progress`), and runs the **apply** step (e.g. OpenClaw writes triage + sections).
- After apply succeeds, the backend moves the task to **investigation-complete** and sends a **Telegram approval** card (approve patch / reject).
- **Cursor handoff** is generated automatically and saved to `docs/agents/cursor-handoffs/cursor-handoff-{task_id}.md` (best-effort; does not block).

**If you need to trigger by hand:** Use the agent/scheduler APIs or run the executor once with the right callbacks; see [task-execution-flow.md](../agents/task-execution-flow.md) and [agent_task_executor.py](../../backend/app/services/agent_task_executor.py).

### 3. Approve the patch in Telegram

- In Telegram, open the approval message for the task and tap **Approve** (patch approval). Backend moves the task to **ready-for-patch**.

### 4. Run the Cursor Bridge (apply code in Cursor)

Choose one:

- **Telegram:** In the same approval flow, tap **"🛠️ Run Cursor Bridge"** (shown when a handoff file exists for that task). Backend calls the Cursor Bridge, which provisions staging, invokes Cursor CLI with the handoff prompt, captures diff, runs tests, and ingests results into Notion.
- **API (from your machine or CI):**
  ```bash
  curl -X POST "https://dashboard.hilovivo.com/api/agent/cursor-bridge/run" \
    -H "Content-Type: application/json" \
    -d '{"task_id": "YOUR_NOTION_PAGE_ID"}'
  ```
  Use the task’s Notion page ID (e.g. `5f1c9779-c707-4dd1-9fc3-801cda6dd55e`). Backend must have `CURSOR_BRIDGE_ENABLED=true` and the handoff at `docs/agents/cursor-handoffs/cursor-handoff-{task_id}.md`.

After a successful run, the backend moves the task to **awaiting-deploy-approval** and sends a **deploy approval** card to Telegram.

### 5. Approve deploy in Telegram

- In Telegram, open the deploy approval and tap **Approve**. Backend moves the task to **deploying** and calls `trigger_deploy_workflow` (dispatches the configured GitHub Actions deploy workflow, e.g. `deploy_session_manager.yml`).

### 6. Deployment runs

- GitHub Actions runs the deploy workflow (sync code, deploy to EC2, etc.). No extra action required unless the workflow fails; then fix and re-run or trigger again.

### 7. Complete the task (smoke check → done)

The task stays in **deploying** until a **smoke check** runs and updates Notion:

- **Automatic:** If the deploy workflow sends a `workflow_run` event to your backend (e.g. `POST .../api/github/actions`) and `GITHUB_WEBHOOK_SECRET` is set, the backend runs the smoke check and moves the task to **done** (or **blocked** if the check fails).
- **Manual:** In Telegram, on the task’s approval card, tap **Smoke Check**. Backend runs the health check and sets the task to **done** or **blocked**.
- **Recovery:** If `AGENT_RECOVERY_ENABLED=true`, the scheduler can run an “orphan smoke” playbook for tasks stuck in **deploying** for a long time.

See [TASK_STUCK_IN_DEPLOYING.md](TASK_STUCK_IN_DEPLOYING.md) if the task never leaves **deploying**.

---

## Task stuck in Planned (scheduler not picking up)

If the task stays **Planned** and the scheduler never claims it:

**Where the Notion secret and database ID are stored:** See [secrets_runtime_env.md § Where the Notion secret and database ID are stored](secrets_runtime_env.md#where-the-notion-secret-and-database-id-are-stored). In short: **NOTION_API_KEY** (the secret) lives in `backend/.env` when running locally, and in `secrets/runtime.env` on the server; **NOTION_TASK_DB** (database ID) can be in the same files or passed as env when running the pickup script. Never commit those files.

### 1. Set NOTION_TASK_DB on the server

On the **EC2 instance** (PROD), add the database ID to `secrets/runtime.env` so the scheduler queries the right Notion database:

```bash
# On EC2 (after connecting via SSM or EC2 Instance Connect)
cd /home/ubuntu/crypto-2.0
echo 'NOTION_TASK_DB=eb90cfa139f94724a8b476315908510a' >> secrets/runtime.env
```

Then restart the backend so it loads the new value:

```bash
docker compose --profile aws restart backend-aws
```

### 2. Run the pickup script on the server

From the **same EC2 session** (repo root). The script runs one scheduler cycle **inside** the backend container, which already has `NOTION_API_KEY` and (after step 1) `NOTION_TASK_DB` from `secrets/runtime.env`:

```bash
cd /home/ubuntu/crypto-2.0
./scripts/run_notion_task_pickup.sh
```

If Docker is available and `backend-aws` is up, the script executes the cycle in the container. After a successful run, the task in Notion should move to **In Progress** then **Investigation Complete**, and the Telegram approval should be sent.

### 3. Optional: verify Notion connection on the server

To confirm the backend can reach Notion before running the pickup:

```bash
docker compose --profile aws exec backend-aws python scripts/check_notion_connection.py
```

### 4. Alternative: run one cycle inside the container

If you prefer not to use the script:

```bash
docker compose --profile aws exec -e NOTION_TASK_DB=eb90cfa139f94724a8b476315908510a backend-aws python -c "
from app.services.agent_scheduler import run_agent_scheduler_cycle
import json
print(json.dumps(run_agent_scheduler_cycle(), default=str, indent=2))
"
```

**Local runs:** Only if you have `NOTION_API_KEY` and `NOTION_TASK_DB` in `backend/.env` or `secrets/runtime.env` locally can you run `./scripts/run_notion_task_pickup.sh` from your Mac. Normally the key is only on the server.

---

## Quick path: use an existing handoff (e.g. Telegram task)

If a task already has a Cursor handoff (e.g. **Investigate Telegram failure**):

1. **Notion:** Set the task to **ready-for-patch** (or approve the patch in Telegram so the backend sets it).
2. **Run Cursor Bridge:**
   - Telegram: tap **"🛠️ Run Cursor Bridge"** on the approval card, or  
   - API: `POST /api/agent/cursor-bridge/run` with `{"task_id": "5f1c9779-c707-4dd1-9fc3-801cda6dd55e"}` (replace with your task ID).
3. After tests pass, the backend moves to **awaiting-deploy-approval** and sends the deploy approval to Telegram.
4. In Telegram, approve deploy → backend triggers deploy workflow.
5. After deploy, run **Smoke Check** in Telegram (or rely on GitHub webhook) → task moves to **done**.

Handoff file for the Telegram example: `docs/agents/cursor-handoffs/cursor-handoff-5f1c9779-c707-4dd1-9fc3-801cda6dd55e.md`.

---

## Key files and endpoints

| What | Where |
|------|--------|
| Cursor handoffs | `docs/agents/cursor-handoffs/cursor-handoff-{task_id}.md` |
| Handoff index | `docs/agents/cursor-handoffs/README.md` |
| Run Cursor Bridge | `POST /api/agent/cursor-bridge/run` body `{"task_id": "<notion_page_id>"}` |
| Bridge diagnostics | `GET /api/agent/cursor-bridge/diagnostics` |
| Bridge events | `GET /api/agent/ops/cursor-bridge-events?limit=10` |
| Smoke check (API) | `POST /api/agent/ops/run-smoke-check` (body with `task_id` if needed) |
| Deploy trigger | Backend `trigger_deploy_workflow()` → GitHub Actions `workflow_dispatch` (e.g. `deploy_session_manager.yml`) |
| Task lifecycle | [task-execution-flow.md](../agents/task-execution-flow.md), [notion-task-intake.md](../agents/notion-task-intake.md) |
| Notion → Cursor | [NOTION_A_CURSOR.md](../agents/NOTION_A_CURSOR.md) |
| Cursor Bridge usage | [cursor-bridge/README.md](../agents/cursor-bridge/README.md) |
| Debugging orchestration | [PRODUCTION_ORCHESTRATION_DEBUGGING_GUIDE.md](PRODUCTION_ORCHESTRATION_DEBUGGING_GUIDE.md) |

---

## Troubleshooting

- **No Cursor handoff:** Ensure the task was prepared with the extended-lifecycle flow (investigation step ran). Check `docs/agents/cursor-handoffs/` for `cursor-handoff-{task_id}.md`. For triage-only tasks, handoff may be created from triage note (see [NOTION_A_CURSOR.md](../agents/NOTION_A_CURSOR.md)).
- **Cursor Bridge disabled:** Set `CURSOR_BRIDGE_ENABLED=true` on the backend and ensure Cursor CLI is available at `CURSOR_CLI_PATH`.
- **Task stuck in deploying:** See [TASK_STUCK_IN_DEPLOYING.md](TASK_STUCK_IN_DEPLOYING.md): run **Smoke Check** in Telegram or fix the GitHub webhook.
- **Logs:** Backend container logs (e.g. `docker compose --profile aws logs -f backend-aws`) and [PRODUCTION_ORCHESTRATION_DEBUGGING_GUIDE.md](PRODUCTION_ORCHESTRATION_DEBUGGING_GUIDE.md) for grep patterns (Cursor handoff, deploy gate, trigger_deploy, smoke_check).

# Jarvis LangGraph MVP — dashboard & API

Read-only multi-agent task pipeline (supervisor → planner → executor → reviewer → cost guard) with PostgreSQL task history.

## Architecture overview

```
POST /api/jarvis/task
        │
        ▼
  run_jarvis_task()          ← JARVIS_ENABLED / JARVIS_DRY_RUN_ONLY gates
        │
        ▼
  LangGraph StateGraph
  ┌─────────────┐
  │ supervisor  │── high risk? ──► cost_guard ──► END
  └──────┬──────┘
         ▼
  ┌─────────────┐     ┌──────────┐     ┌──────────┐     ┌────────────┐
  │   planner   │ ──► │ executor │ ──► │ reviewer │ ──► │ cost_guard │
  └─────────────┘     └──────────┘     └──────────┘     └────────────┘
        │                   │
        │                   └── read-only tools (health, logs, repo read)
        └── Bedrock (optional) or heuristic fallback
        │
        ▼
  jarvis_task_runs (PostgreSQL) — record_task_started / record_task_completed
```

| Component | Path |
|-----------|------|
| API routes | `backend/app/api/routes_jarvis.py` |
| Service | `backend/app/jarvis/mvp/service.py` |
| LangGraph | `backend/app/jarvis/mvp/graph.py`, `agents.py` |
| Risk | `backend/app/jarvis/mvp/risk.py` |
| Persistence | `backend/app/jarvis/mvp/persistence.py`, `database.ensure_jarvis_task_runs_table` |
| Dashboard | `frontend/src/app/jarvis/page.tsx` |
| API client | `frontend/src/lib/api.ts` (`submitJarvisTask`, `listJarvisTasks`, `getJarvisTask`) |

Legacy `POST /jarvis` (`app.jarvis.orchestrator`) is unchanged and independent of this pipeline.

## Dashboard route

- **URL:** `/jarvis`
- **Navigation:** Monitoring page header link **Jarvis Tasks**, or open `/jarvis` directly.
- **Back link:** Jarvis page links to `/monitoring`.

## Run a task from the UI

1. Open `/jarvis`.
2. Enter a natural-language task (e.g. `check dashboard health and runtime status`).
3. **Dry run** is always enabled in PROD (`JARVIS_DRY_RUN_ONLY=true`); the checkbox is shown but disabled.
4. Click **Run Jarvis Task**.
5. Wait for the loading state; on success the history table refreshes and the detail panel opens for the new run.

## View task history

- The **Task history** table lists the 20 most recent **completed** runs (`GET /api/jarvis/tasks?limit=20`).
- Columns: created_at, task, status, risk_level, estimated_cost_usd, completed_at, View action.
- Click **View** (or run a new task) to load the **Task detail** panel (`GET /api/jarvis/tasks/{task_id}`).
- Detail fields: task_id, task, status, risk_level, dry_run, plan, tool_results, review, estimated_cost_usd, final_answer, error, created_at, completed_at.

## API endpoints

| Method | Path | Purpose |
|--------|------|---------|
| `POST` | `/api/jarvis/task` | Run one MVP task (`task`, `dry_run`) |
| `GET` | `/api/jarvis/tasks?limit=20` | List recent completed runs |
| `GET` | `/api/jarvis/tasks/{task_id}` | Full run detail |

Legacy `POST /jarvis` (memory → plan → tools orchestrator) is unchanged and not used by this dashboard.

## Safety behavior

| Setting | Effect |
|---------|--------|
| `JARVIS_ENABLED=false` | Tasks return `failed` with a disabled message |
| `JARVIS_DRY_RUN_ONLY=true` | Non-dry-run requests return `requires_approval`; UI always sends `dry_run: true` |
| High-risk keywords (delete, terminate, trade, secrets/IAM) | `requires_approval`, empty plan/tool_results, no tools executed |
| Medium risk | Warning styling; may complete with read-only tools |
| Low risk | Normal styling; read-only tools from allowlist only |

No write-capable tools are exposed through this MVP. Responses do not include secrets or raw environment variables.

## Manual QA checklist

- [ ] `/jarvis` loads with task form, history table, and dry-run checkbox (disabled).
- [ ] Low-risk task (`check dashboard health and runtime status`) completes; history refreshes; detail shows plan and tool_results.
- [ ] High-risk task (`terminate the ec2 instance in production`) shows `requires_approval`, high risk, empty plan/tool_results.
- [ ] API errors (e.g. DB unavailable) show a clear message in the red alert banner.
- [ ] Legacy `POST /jarvis` still works independently (not exercised by this page).

## Environment

```bash
JARVIS_ENABLED=true
JARVIS_DRY_RUN_ONLY=true
```

Optional Bedrock: `AWS_REGION`, `BEDROCK_MODEL_ID` (heuristic fallbacks work when Bedrock is unavailable).

| Variable | Default | Purpose |
|----------|---------|---------|
| `JARVIS_ENABLED` | `true` | Master switch for MVP task execution |
| `JARVIS_DRY_RUN_ONLY` | `true` | Block non-dry-run requests (`requires_approval`) |
| `AWS_REGION` / `JARVIS_BEDROCK_REGION` | — | Bedrock region |
| `BEDROCK_MODEL_ID` / `JARVIS_BEDROCK_MODEL_ID` | — | Bedrock model for planner/reviewer |
| `DATABASE_URL` | required in AWS | PostgreSQL for `jarvis_task_runs` |

## Persistence schema

Table `jarvis_task_runs` is created at boot via `ensure_jarvis_task_runs_table()` (no separate migration file).

| Column | Type (PostgreSQL) | Notes |
|--------|-------------------|-------|
| `id` | SERIAL | Primary key |
| `task_id` | TEXT UNIQUE | UUID from service |
| `task` | TEXT | User task text |
| `status` | TEXT | `completed`, `requires_approval`, `failed`, `running` |
| `risk_level` | TEXT | `low`, `medium`, `high` |
| `dry_run` | BOOLEAN | Request flag |
| `plan_json` | JSONB | Planner steps |
| `tool_results_json` | JSONB | Read-only tool outputs |
| `review_json` | JSONB | Reviewer summary |
| `estimated_cost_usd` | NUMERIC | Cost guard estimate |
| `final_answer` | TEXT | User-facing result |
| `error` | TEXT | Failure detail |
| `created_at` | TIMESTAMPTZ | Insert time |
| `completed_at` | TIMESTAMPTZ | Null while running |

Indexes: `ix_jarvis_task_runs_status`, `ix_jarvis_task_runs_created_at`.

## Deployment notes

1. **Trigger:** Push to `main` runs `.github/workflows/deploy_session_manager.yml` (SSM deploy to EC2).
2. **Backend:** `docker compose --profile aws build` installs `langgraph` and `langchain-core` from `backend/requirements.txt`.
3. **Secrets:** `scripts/aws/render_runtime_env.sh` renders `secrets/runtime.env` from SSM; ensure `DATABASE_URL`, `JARVIS_ENABLED=true`, and `JARVIS_DRY_RUN_ONLY=true` are present for PROD.
4. **Frontend:** Jarvis dashboard is in this repo under `frontend/src/app/jarvis/`. The deploy workflow also clones `ccruz0/frontend` — keep both in sync or the in-repo frontend will be overwritten on deploy until the external repo includes `/jarvis`.
5. **Boot:** Backend creates `jarvis_task_runs` on startup if missing; no manual migration step.
6. **Health:** After deploy, verify `GET /api/health` and `GET /jarvis` return 200.

## Known limitations

- **Dry-run only in PROD:** `JARVIS_DRY_RUN_ONLY=true` blocks live execution; no autonomous runs.
- **Read-only tools:** No write-capable AWS tools; high-risk keywords short-circuit to `requires_approval`.
- **Bedrock optional:** Planner/reviewer use heuristics when Bedrock is unavailable (reduced quality, still safe).
- **Completed history only:** `GET /api/jarvis/tasks` lists runs with `completed_at IS NOT NULL` (in-flight runs excluded).
- **Legacy coexistence:** `POST /jarvis` orchestrator and Telegram/Perico flows are separate; do not modify them from this MVP.
- **External frontend clone:** Deploy workflow replaces `frontend/` with `ccruz0/frontend` — document and track Jarvis UI changes in both repos until unified.

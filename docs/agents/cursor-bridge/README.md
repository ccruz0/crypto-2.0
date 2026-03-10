# Cursor Execution Bridge

Phase 1–2 implementation of the [Cursor Execution Bridge](../architecture/CURSOR_EXECUTION_BRIDGE_DESIGN.md).

## Quick Start

1. **Enable the bridge:**
   ```bash
   export CURSOR_BRIDGE_ENABLED=true
   ```

2. **Ensure a Cursor handoff exists** for your task:
   - `docs/agents/cursor-handoffs/cursor-handoff-{task_id}.md`

3. **Trigger via API (Phase 2 = invoke + diff + tests):**
   ```bash
   curl -X POST http://localhost:8002/api/agent/cursor-bridge/run \
     -H "Content-Type: application/json" \
     -d '{"task_id": "YOUR_NOTION_PAGE_ID"}'
   ```

4. **Phase 1 only (invoke, no tests):**
   ```bash
   curl -X POST http://localhost:8002/api/agent/cursor-bridge/run \
     -H "Content-Type: application/json" \
     -d '{"task_id": "YOUR_NOTION_PAGE_ID", "phase": 1}'
   ```

5. **With PR creation (creates branch, commits, pushes, opens PR):**
   ```bash
   curl -X POST http://localhost:8002/api/agent/cursor-bridge/run \
     -H "Content-Type: application/json" \
     -d '{"task_id": "YOUR_NOTION_PAGE_ID", "create_pr": true}'
   ```
   Requires `GITHUB_TOKEN` with `repo` scope. PR created only when tests pass.

6. **Check events:**
   ```bash
   curl http://localhost:8002/api/agent/ops/cursor-bridge-events?limit=10
   ```

7. **Check readiness (diagnostics):**
   ```bash
   curl http://localhost:8002/api/agent/cursor-bridge/diagnostics
   ```
   Returns `enabled`, `cursor_cli_found`, `staging_root_writable`, `ready`, etc.

## When is the action sent to Cursor?

The Cursor CLI is invoked (action sent to Cursor) only in these cases:

| Trigger | When it happens |
|--------|------------------|
| **Telegram** | You tap **"🛠️ Run Cursor Bridge"** in the approval card. The button appears after you approve the patch (task → ready-for-patch) and only if `docs/agents/cursor-handoffs/cursor-handoff-{task_id}.md` exists. |
| **Scheduler (optional)** | When `CURSOR_BRIDGE_AUTO_IN_ADVANCE=true`, the agent scheduler runs `advance_ready_for_patch_task` for tasks in **ready-for-patch**. If the handoff file exists and the bridge is enabled, it runs the bridge automatically (no button click). |
| **API** | When something calls **POST /api/agent/cursor-bridge/run** with `task_id` (e.g. dashboard, script, or webhook). |

There is no automatic “after investigation complete, send to Cursor” — it is always one of: manual Telegram button, optional scheduler auto-run, or explicit API call.

**Recommended:** Use the **manual** Telegram button. Leave `CURSOR_BRIDGE_AUTO_IN_ADVANCE` unset or `false` so the bridge runs only when you tap "Run Cursor Bridge" after reviewing the investigation and approving the patch.

## Outputs

- **Diff:** `docs/agents/patches/{task_id}.diff` (when Cursor makes changes)
- **Tests:** Backend `pytest -q`, frontend `npm run lint` + `npm run build`
- **Notion:** `record_test_result` writes Test Status; `cursor_patch_url` set when diff exists (or PR URL when `create_pr=true`); task advances to `awaiting-deploy-approval` when tests pass
- **PR:** When `create_pr=true` and tests pass, creates branch `cursor-patch-{task_id}`, commits, pushes, and opens PR via GitHub API
- **Scheduler:** When `CURSOR_BRIDGE_AUTO_IN_ADVANCE=true`, `advance_ready_for_patch_task` runs the bridge automatically for tasks with a cursor handoff; on success, sends deploy approval to Telegram
- **Telegram:** After approving a patch, a "🛠️ Run Cursor Bridge" button appears when a handoff exists; click to run the bridge manually

## Requirements

- Cursor CLI installed (`cursor` in PATH or `npx cursor`)
- For PR creation: `GITHUB_TOKEN` with `repo` scope
- Git available for cloning
- Python + pytest for backend tests
- Node + npm for frontend tests
- `ATP_STAGING_ROOT` writable (default: `/tmp/atp-staging`)

## Environment Variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `CURSOR_BRIDGE_ENABLED` | `false` | Master switch |
| `ATP_STAGING_ROOT` | `/tmp/atp-staging` | Staging root |
| `CURSOR_CLI_PATH` | `cursor` | Cursor binary |
| `CURSOR_CLI_TIMEOUT` | `300` | Cursor timeout (seconds) |
| `CURSOR_BRIDGE_TEST_TIMEOUT` | `120` | Per-suite test timeout (seconds) |
| `CURSOR_BRIDGE_AUTO_IN_ADVANCE` | `false` | When true, scheduler runs bridge automatically for ready-for-patch tasks with handoff |

## Cleanup

Staging directories are not auto-removed after use. To clean up manually:

```python
from app.services.cursor_execution_bridge import cleanup_staging
cleanup_staging("task-id-here")
```

Or remove the staging root directly:
```bash
rm -rf /tmp/atp-staging/atp-*
```

## Troubleshooting

See [CURSOR_EXECUTION_BRIDGE_DESIGN.md §11 Troubleshooting](../architecture/CURSOR_EXECUTION_BRIDGE_DESIGN.md#11-troubleshooting).

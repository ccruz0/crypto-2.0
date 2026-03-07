# Notion Connection Check

Small runbook to verify backend-side Notion integration for the **AI Task System** database.

## Required environment variables

- `NOTION_API_KEY` - Notion integration token
- `NOTION_TASK_DB` - Notion database ID

## 1) Verify Notion access

From repo root:

```bash
source backend/.venv/bin/activate
python backend/scripts/check_notion_connection.py
```

Expected success output:

- `RESULT: PASS - Notion database access is working.`
- summary line with metadata/query status

## 2) Run one scheduler cycle safely

From repo root:

```bash
source backend/.venv/bin/activate
python backend/scripts/run_agent_scheduler_cycle.py
```

Expected behavior:

- If there are planned tasks and approvals/callbacks are configured, it prepares one task.
- If there are no planned tasks, it returns:
  - `"ok": true`
  - `"action": "none"`
  - `"reason": "no task"`

## Common failure causes

- Missing `NOTION_API_KEY`
- Missing `NOTION_TASK_DB`
- Database not shared with the OpenClaw Notion integration
- Integration does not have required read permissions on that database
# Notion connection check

A small operational script to verify end-to-end Notion connectivity for the current backend environment. It uses the same configuration and API surface as the agent/scheduler flow.

**Script:** `backend/scripts/check_notion_connection.py`

---

## Required environment variables

- **NOTION_API_KEY** — Notion integration token (required for any API call).
- **NOTION_TASK_DB** — Notion database ID for the "AI Task System" database (required for query and comments).

The script does **not** print or log these values.

---

## Command to run

From the backend directory (with env loaded, e.g. from `.env`):

```bash
cd backend
python scripts/check_notion_connection.py
```

From repo root:

```bash
python backend/scripts/check_notion_connection.py
```

Optional write test (append a diagnostic comment to a specific task page):

```bash
python scripts/check_notion_connection.py --write-test <NOTION_PAGE_ID>
```

If you pass `--write-test` without a page ID, the script skips the write and reports `comments writable: skipped (no PAGE_ID; use --write-test <page_id>)`.

---

## Expected success output

When all required checks pass (env set, database reachable, read succeeds):

```
Notion connection check
-----------------------
  env vars present:   yes
  database reachable: yes
  read tasks:         yes
  comments writable:  skipped
```

With `--write-test <page_id>` and write succeeding:

```
  comments writable:  yes
```

Exit code is **0** only when every required check passes (and, if write test was requested with a page ID, the write also succeeds).

---

## Common failure causes

| Symptom | Likely cause |
|--------|----------------|
| `env vars present: no` | `NOTION_API_KEY` and/or `NOTION_TASK_DB` not set or empty in the environment (e.g. cron without sourcing `.env`). |
| `database reachable: no` | Network/firewall blocking Notion API; wrong database ID; integration not shared with the database. |
| `read tasks: no` | Same as above; or Notion returned an error (e.g. 401 invalid token, 404 database not found). The script does not log response bodies to avoid leaking secrets. |
| `comments writable: no` | Write test failed: invalid page ID, page not shared with the integration, or Notion API error. |

---

## Optional write-test usage

- Use **only** when you need to confirm that the backend can append comments to a Notion page (e.g. scheduler/executor comments).
- Pass a **real task page ID** (UUID of an existing page in your task database). The script appends a single line: `[check_notion_connection] Diagnostic comment; safe to delete.`
- Do **not** run with `--write-test` in cron or by default; it is for manual diagnostics only.
- If you omit the page ID after `--write-test`, no write is performed and the script only reports that the write was skipped.

---

## Related

- `backend/app/services/notion_task_reader.py` — Read pending tasks.
- `backend/app/services/notion_tasks.py` — Create tasks and status/comment helpers.
- [Agent scheduler](agent-scheduler.md) — Uses the same Notion config and comments.

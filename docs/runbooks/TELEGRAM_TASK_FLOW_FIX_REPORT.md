# Telegram /task Flow Fix Report

**Date:** 2025-03-19  
**Scope:** `/task <description>` in ATP Control — end-to-end fix and verification.

---

## Root Cause

1. **"Low impact and was not created"** — This message does **not** exist in the current source. It was removed in a prior fix (see `docs/runbooks/TASK_IMPACT_CLASSIFIER_FIX.md`). If you still see it in production, the runtime is using **stale deployed code**. Deploy the current codebase to fix.

2. **Notion not configured** — When `NOTION_API_KEY` or `NOTION_TASK_DB` are missing, `create_task_from_telegram_intent` returns `{"ok": False, "error": "Notion is not configured"}`. The Telegram handler already had special handling for this, but lacked:
   - A visible debug marker to prove production uses updated code
   - Best-effort SSM repair before failing (LAB can recover from SSM)

3. **No high-signal debug logging** — Hard to trace `/task` flow in production logs.

---

## Files Changed

| File | Change |
|------|--------|
| `backend/app/services/telegram_commands.py` | Added debug logging, `[task-debug-v4]` marker in Notion-not-configured error, try SSM repair before create |
| `backend/tests/test_telegram_task_command.py` | Added `test_handle_task_command_notion_not_configured_returns_debug_marker`, `test_handle_task_command_fallback_stored_message` |

---

## Behavior Before / After

### Before
- `/task` with missing Notion → "⚠️ Task could not be created because Notion is not configured..."
- No debug logging for raw text, normalized command, or create result
- No attempt to repair Notion env from SSM before failing
- No visible marker to prove updated code in production

### After
- `/task` with missing Notion → "[task-debug-v4] ⚠️ Task could not be created because Notion is not configured. Set NOTION_API_KEY and NOTION_TASK_DB in .env (local) or SSM (AWS)..."
- High-signal logs: `[TG][TASK][DEBUG] raw_text=... normalized_cmd=...`, `create_task_from_telegram_intent result ok=... error=...`, `user_facing_message=...`
- Best-effort `try_repair_notion_env_from_ssm()` when Notion missing (LAB can recover)
- `[task-debug-v4]` in error message proves production is using updated code

### Unchanged (verified correct)
- Empty intent → usage message
- Notion configured + task compiles → create or reuse task
- Notion API fails but fallback store works → "Notion unavailable. Task stored locally and will be synced automatically."
- Low-impact tasks → created with `status=backlog`, `priority=low` (never rejected)
- `/task` never falls through to "Unknown command"

---

## Notion Configuration

### Where credentials come from

| Environment | Source |
|-------------|--------|
| **Local dev** | `backend/.env` or `secrets/runtime.env` — add `NOTION_API_KEY` and `NOTION_TASK_DB` manually |
| **AWS (prod)** | `scripts/aws/render_runtime_env.sh` fetches from SSM: `/automated-trading-platform/prod/notion/api_key`, `/automated-trading-platform/prod/notion/task_db` |
| **LAB** | SSM: `/automated-trading-platform/lab/notion/api_key`; `NOTION_TASK_DB` defaults to `eb90cfa139f94724a8b476315908510a` |
| **Runtime repair** | `notion_env.try_repair_notion_env_from_ssm()` — fetches LAB SSM and sets `os.environ` |

### If credentials are missing

**Local:** Add to `backend/.env` (use exact var names; values from Notion Settings → Integrations and DB URL):
- `NOTION_API_KEY` — integration token
- `NOTION_TASK_DB` — database ID, e.g. `eb90cfa139f94724a8b476315908510a`

**AWS:** Ensure SSM parameters exist and `render_runtime_env.sh` runs before backend start. If not, add to SSM or run `scripts/aws/lab_notion_oneliner_ssm.sh` (LAB).

**Cannot recover from repo:** `NOTION_API_KEY` and `NOTION_TASK_DB` are secrets. They are not in the repo. You must provide them via env, .env, or SSM.

---

## Tests Added/Updated

- `test_handle_task_command_notion_not_configured_returns_debug_marker` — Ensures `[task-debug-v4]` appears in Notion-not-configured error
- `test_handle_task_command_fallback_stored_message` — Ensures fallback-stored path shows "stored locally" and "synced automatically"

Existing tests already cover:
- `/task` routes correctly, never unknown command
- Low-impact tasks created as backlog (`test_task_value_gate.py::TestCreationGate::test_low_value_task_created_queued`)

---

## What Still Requires Your Input

**If you see "[task-debug-v4]" in the Telegram error:** Production is using the updated code. The issue is missing Notion credentials. Provide:

1. **NOTION_API_KEY** — Notion integration token (from Notion → Settings → Integrations)
2. **NOTION_TASK_DB** — Notion database ID for the "AI Task System" database (from the database URL: `notion.so/.../{DATABASE_ID}?v=...`)

Add them to:
- **Local:** `backend/.env`
- **AWS:** SSM parameters (or `.env.aws` if not using SSM for Notion)

**If you never see "[task-debug-v4]":** Production is still running old code. Redeploy the backend.

---

## Temporary Marker

The `[task-debug-v4]` marker is temporary. Remove it once you've confirmed production is using the updated code and Notion is configured.

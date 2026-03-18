# Task Compiler: Fallback & Recovery

Production-safe Telegram → Notion task creation: no silent failures, graceful degradation, auto-retry.

---

## Flow: Success vs Failure vs Recovery

```
                    Telegram /task <intent>
                              │
                              ▼
                    ┌─────────────────────┐
                    │ notion_is_configured?│
                    └──────────┬──────────┘
               ┌──────────────┼──────────────┐
               │ No           │              │ Yes
               ▼              │              ▼
    ┌──────────────────┐     │     ┌────────────────────┐
    │ Return error      │     │     │ create_notion_task  │
    │ "Notion is not    │     │     └─────────┬──────────┘
    │  configured"      │     │               │
    │ TG: long message  │     │     ┌─────────┴─────────┐
    │ log:              │     │     │ Success            │ Failure (None)
    │ notion_preflight  │     │     ▼                   ▼
    │ _failed           │     │  Notion page     store_fallback_task(task)
    └──────────────────┘     │  Return ok       Return { fallback_stored: true }
                             │  TG: success     TG: "Notion unavailable. Task
                             │                  stored locally and will be
                             │                  synced automatically."
                             │                  log: notion_task_creation_failed
                             │                  log: fallback_task_created
                             │
                             │     ┌────────────────────────────────────────┐
                             │     │ Scheduler cycle (each run)              │
                             │     │ retry_failed_notion_tasks()             │
                             │     │   → get_pending_fallback_tasks()       │
                             │     │   → for each: create_notion_task()      │
                             │     │   → on success: remove_fallback_task()  │
                             │     │   → log: fallback_task_synced          │
                             │     └────────────────────────────────────────┘
                             │
                             └──► User always gets a clear Telegram response
```

---

## Example: Telegram → Fallback → Retry → Notion Success

1. **Notion is down or NOTION_TASK_DB missing.** User sends:
   ```
   /task Investigate why alerts are not sent when buy conditions are met
   ```
2. **Preflight:** `notion_is_configured()` is false → return `{ "ok": false, "error": "Notion is not configured" }` → Telegram shows: *"Task could not be created because Notion is not configured. The system is still operational, but task tracking is disabled."*

3. **Notion is up but create fails (e.g. API error):** Same `/task` → `create_notion_task()` returns `None` → `store_fallback_task(task)` writes to `app/data/task_fallback.json` (or `TASK_FALLBACK_STORE_PATH`) → Telegram shows: *"Notion unavailable. Task stored locally and will be synced automatically."*

4. **Next scheduler cycle:** `retry_failed_notion_tasks()` runs → reads pending entries → calls `create_notion_task()` for each → on success, removes from fallback and logs `fallback_task_synced task_id=...`.

5. **Result:** Task appears in Notion; auto-promote (same or next cycle) can move it to Ready for Investigation; pipeline continues.

---

## Logging (no silent failures)

| Log event | When |
|-----------|------|
| `notion_preflight_failed` | NOTION_API_KEY or NOTION_TASK_DB missing before create |
| `notion_task_creation_failed` | create_notion_task returned None (API/dedup) |
| `fallback_task_created` | Task stored to local JSON after Notion failure |
| `fallback_task_synced` | A fallback task was successfully pushed to Notion and removed from store |

---

## Files

| File | Purpose |
|------|---------|
| `backend/app/services/task_compiler.py` | Preflight, create, fallback store on failure, `retry_failed_notion_tasks()` |
| `backend/app/services/task_fallback_store.py` | JSON store: `store_fallback_task`, `get_pending_fallback_tasks`, `remove_fallback_task` |
| `backend/app/services/notion_tasks.py` | `notion_is_configured()` |
| `backend/app/services/telegram_commands.py` | User-facing messages for Notion not configured / fallback stored |
| `backend/app/services/agent_scheduler.py` | Calls `retry_failed_notion_tasks()` each cycle (before promote) |

---

## Config

- **TASK_FALLBACK_STORE_PATH** (optional): Path to JSON file for fallback tasks. Default: `backend/app/data/task_fallback.json`.

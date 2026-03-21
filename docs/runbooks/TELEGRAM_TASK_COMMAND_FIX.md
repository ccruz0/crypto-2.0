# Telegram /task Command Fix

## Root Cause

The `/task` command had split routing logic:
- Multiple handler branches (`text_lower.startswith("/task ")`, `text_lower.startswith("/task")`, `handler_name == "task"`)
- Fallback branches that could show "Unknown command" if router matched but handler checks failed (e.g. encoding quirks)
- No single canonical path; `/task` could fall through to unknown-command in edge cases

## Fix

1. **Single canonical handler**: `_handle_task_command()` — one function for all `/task` variants
2. **Router-first dispatch**: When `handler_name == "task"`, dispatch immediately and return; never fall through to other handlers
3. **Robust normalization**: Strip zero-width chars (`\u200b\u200c\u200d\ufeff`) from command text; preserve `@botname` stripping
4. **Strong logging**: `[TG][CMD]`, `[TG][ROUTER]`, `[TG][TASK]`, `[TG][UNKNOWN]` — grep-friendly

## Files Changed

- `backend/app/services/telegram_commands.py`: `_handle_task_command`, router-first dispatch, normalization, logging
- `backend/tests/test_telegram_task_command.py`: `_handle_task_command` tests, `@botname` normalization test
- `backend/tests/test_telegram_approval_callback.py`: `TestTaskTextRouting` — `/task` routes to handler, unknown still works, `/help` works

## Verification (AWS Logs)

```bash
# /task routed to task handler (never unknown)
grep "\[TG\]\[ROUTER\] selected_handler=task" logs/*.log
grep "\[TG\]\[TASK\] handler=task start" logs/*.log

# Unknown command only for non-task
grep "\[TG\]\[UNKNOWN\] telegram_unknown_command" logs/*.log

# Raw incoming text
grep "\[TG\]\[TEXT\]" logs/*.log
grep "\[TG\]\[CMD\] telegram_command_detected" logs/*.log
```

## Rollback

Revert commits that introduced `_handle_task_command` and router-first dispatch. The previous logic had multiple `/task` branches in the handler chain; restore those if needed.

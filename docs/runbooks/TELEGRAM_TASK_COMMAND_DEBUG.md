# Debug: /task returns "Unknown command. Use /help."

## Where "Unknown command" is sent

**File:** `backend/app/services/telegram_commands.py`  
**Function:** `handle_telegram_update()`  
**Lines:** ~5313 (branch `elif text.startswith("/")`) and ~5320 (branch `else`).

The bot sends that message only when the **handler chain** reaches the generic "unknown" or "fallback" branch — i.e. no earlier branch (including `/task`) matched.

## Root cause (why /task can hit "unknown")

One of these is true when you see "Unknown command" for `/task`:

1. **Stale runtime**  
   The process/container running the backend was started before the `/task` handler was added or updated. The code that runs has no `text_lower.startswith("/task")` (or equivalent) branch, so `/task` falls through to the generic `/` branch.

2. **Command form not matching**  
   The incoming `message.text` is not what we expect, e.g.:
   - Different casing and old code (e.g. `/Task`) with only `text.startswith("/task")`.
   - Command with `@BotName` and normalization not applied or failing.
   - Leading/trailing spaces or encoding so that `(text or "").strip().lower()` never starts with `"/task"`.

3. **Wrong code path**  
   The update is processed by a different entry point that does not use the same handler chain (e.g. another service or an old webhook). In this codebase, the only path that sends "Unknown command. Use /help." is `handle_telegram_update` in `telegram_commands.py`.

## Exact blocking point

- **Place:** `handle_telegram_update()` in `telegram_commands.py`, inside the big `try` block that dispatches on `text` / `text_lower` / `handler_name`.
- **What happens:** For the update that contained `/task`, either:
  - The **router** never set `handler_name = "task"` (so `text_lower`/`cmd_token` didn’t match our `/task` conditions), or
  - The **handler** chain didn’t run the `/task` branch (e.g. no `elif` for `/task` in the running code, or condition not satisfied), so execution reaches `elif text.startswith("/")` or `else` and sends "Unknown command. Use /help."

So the “blocking point” is: **the first time that update is handled, the branch that sends "Unknown command. Use /help." is the one that runs**, because no `/task` branch ran before it.

## Debug logs added (to find the exact cause)

After deploying the latest code, reproduce the issue and check logs for:

| Log message | Meaning |
|-------------|--------|
| `telegram_update_received update_id=... chat_id=... text=...` | Raw text of the incoming message. Confirms what the bot received. |
| `telegram_command_detected update_id=... command=... args=...` | Parsed command and args after normalization. Confirms how we parsed it. |
| `[TG][ROUTER] selected_handler=... text_lower=... cmd_lower=...` | Which handler was chosen and the normalized strings. If you see `selected_handler=unknown` for a `/task` message, the router didn’t recognize it. |
| `telegram_unknown_command update_id=... chat_id=... command=... text_repr=...` | Emitted when we are about to send "Unknown command. Use /help." — use this to see the exact `command` and `text` that failed to match. |

From these you can tell:

- If `text` or `command` is not `/task` (e.g. encoding, @botname, or trimming issue) → fix parsing/normalization or add more defensive checks.
- If `selected_handler=task` but you still get "Unknown command" → the handler branch for task might be missing or wrong in the running code (stale build).
- If `selected_handler=unknown` for a message that looks like `/task` → router conditions in the running code don’t match (stale or logic bug); the recent changes add `cmd_lower == "/task"` and a `handler_name == "task"` fallback to reduce this.

## Fixes applied in code

1. **Router:** `/task` is recognized with:
   - `text_lower.startswith("/task ")` / `text_lower.startswith("/task")`
   - **or** `cmd_lower == "/task"` / `cmd_lower.startswith("/task")`  
   so that even with `@BotName` or small variations we still set `handler_name = "task"`.

2. **Handler fallback:** If the router set `handler_name == "task"` but no `text_lower.startswith("/task")` branch ran (e.g. encoding), an `elif handler_name == "task"` branch runs the same task logic (create/reuse task or show usage).

3. **Debug logging:** As above, so you can see exactly what was received and why it was treated as unknown.

## How to verify /task works live

1. **Deploy/restart**  
   Ensure the process/container that runs Telegram polling is running the version that includes the `/task` router and handler and the new logs (rebuild/restart backend or the service that runs `process_telegram_commands`).

2. **Confirm code in the running process**  
   If you can, check that the running code has:
   - The router condition that sets `handler_name = "task"` (e.g. `cmd_lower == "/task"` or `text_lower.startswith("/task")`).
   - The `elif handler_name == "task":` block (or the equivalent `elif text_lower.startswith("/task")` blocks).

3. **Reproduce and check logs**  
   In Telegram, send:
   - `/task`
   - `/task fix order mismatch`  
   Then in backend logs:
   - You should see `telegram_update_received` and `telegram_command_detected` with `command=/task` and the right `args`/intent.
   - You should see `[TG][ROUTER] selected_handler=task ...`.
   - You should **not** see `telegram_unknown_command` for that update.
   - You should see the task usage or the “Task created” (or similar) reply in Telegram.

4. **If it still says "Unknown command"**  
   - Find the update in logs: `telegram_update_received` / `telegram_command_detected` for that moment.
   - Check `telegram_unknown_command` for the same `update_id` and see `command=...` and `text_repr=...`.
   - That shows the exact string that failed to match; adjust normalization or router conditions for that form, or confirm the running code actually contains the `/task` and `handler_name == "task"` logic.

## Files changed (for this fix)

- `backend/app/services/telegram_commands.py`
  - Log: `telegram_update_received` (on message extraction).
  - Log: `telegram_command_detected` (after parsing command/args).
  - Router: `cmd_lower` and match on `cmd_lower == "/task"` or `cmd_lower.startswith("/task")` in addition to `text_lower`.
  - Router log: `selected_handler`, `text_lower`, `cmd_lower`.
  - Handler: `elif handler_name == "task":` fallback that runs task logic when router set task but no string-based branch ran.
  - Log: `telegram_unknown_command` (when sending "Unknown command. Use /help.") with `command`, `text_repr`, and update/chat ids.

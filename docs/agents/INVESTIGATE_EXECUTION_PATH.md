# /investigate Execution Path and Runtime Diagnostics

## Summary

The `/investigate` command can be executed by **two different runtimes**:

1. **backend-aws** (ATP bot) — Polls Telegram via `getUpdates`, processes in `telegram_commands.py` → `agent_telegram_commands.py`. Has `pydantic-settings`; runtime-check passes.
2. **OpenClaw** (Claw bot) — OpenClaw's Telegram channel receives DMs. If a tool/agent runs ATP Python code from the mounted workspace, that runs in the OpenClaw container. Without the ATP wrapper image, `pydantic-settings` is missing → `ModuleNotFoundError`.

**Why runtime-check passes but /investigate fails:** You are messaging the **Claw bot** (OpenClaw), not the ATP bot. The runtime-check runs in backend-aws; /investigate in that case runs in OpenClaw.

---

## Exact Execution Path (backend-aws)

```
Telegram API (getUpdates)
  → process_telegram_commands() [scheduler.py → telegram_commands.py]
  → handle_telegram_update(update, db)
  → text.startswith("/investigate")
  → handle_investigate_command(chat_id, text, send_command_response)
     [agent_telegram_commands.py]
  → parse_investigate(text)
  → route_task_with_reason(prepared_task) [agent_routing.py]
  → select_default_callbacks_for_task(prepared_task) [agent_callbacks.py]
  → _run_apply_and_validate() → openclaw_client HTTP to OpenClaw gateway
```

**Files involved:**

| File | Role |
|------|------|
| `backend/app/services/scheduler.py` | Calls `process_telegram_commands()` periodically |
| `backend/app/services/telegram_commands.py` | Polls `get_telegram_updates()`, dispatches to `handle_investigate_command` |
| `backend/app/services/agent_telegram_commands.py` | Parses, routes, runs apply/validate |
| `backend/app/services/agent_routing.py` | `route_task_with_reason()` |
| `backend/app/services/agent_callbacks.py` | `select_default_callbacks_for_task()`, `_make_openclaw_callback` |
| `backend/app/services/openclaw_client.py` | HTTP client to OpenClaw gateway |

---

## OpenClaw Path (pydantic_settings Error)

When you send `/investigate` to the **Claw bot** (OpenClaw's Telegram DM):

1. OpenClaw receives the message via its `channels.telegram` integration.
2. An agent or tool may invoke ATP Python code (e.g. scripts or `from app...` imports).
3. That Python runs in the **OpenClaw container**, which uses the base image by default.
4. The base image does not include `pydantic-settings` → `ModuleNotFoundError: No module named 'pydantic_settings'`.

**Fix:** Use the ATP wrapper image (`openclaw/Dockerfile.openclaw`), which adds:

```dockerfile
RUN pip3 install --break-system-packages pydantic pydantic-settings requests
```

Deploy with:

```bash
./scripts/openclaw/deploy_openclaw_lab_from_mac.sh
```

See [docs/openclaw/OPENCLAW_TELEGRAM_RESTORE.md](../openclaw/OPENCLAW_TELEGRAM_RESTORE.md).

---

## Diagnostic Implementation

### Runtime identity helper

`backend/app/core/runtime_identity.py`:

- `get_runtime_identity()` — Returns `service`, `hostname`, `container_id`, `python_executable`, `cwd`, `runtime_origin`
- `format_runtime_identity_short()` — One-line summary for logs/Telegram
- No pydantic/config imports; safe in any context

### Structured logs

| Log key | When |
|---------|------|
| `telegram_command_received command=investigate` | When /investigate is about to be dispatched (telegram_commands.py) |
| `command_handler_selected command=investigate` | After routing; includes `selected_agent`, `route_reason`, `fallback_used=false` |
| `fallback_used command=investigate` | When `no_match` or `scaffolded_agent` |
| `runtime_identity command=investigate` | At start of handle_investigate_command |

### Debug preamble

Set `TELEGRAM_INVESTIGATE_DEBUG=true` (or `1`, `yes`) to include a short runtime identity line in the Telegram reply:

```
🔍 [DEBUG] service=backend | host=xxx | python=/usr/bin/python3 | cwd=/app
```

Useful to confirm which runtime is replying.

---

## Minimal Next Fix

**If /investigate returns `ModuleNotFoundError: pydantic_settings`:**

1. **Confirm which bot you're messaging:** ATP bot (same as /status, /portfolio) vs Claw bot (OpenClaw DM).
2. **If Claw bot:** Deploy the ATP wrapper image so OpenClaw has `pydantic-settings`:
   ```bash
   ./scripts/openclaw/deploy_openclaw_lab_from_mac.sh
   ```
3. **If ATP bot:** Rebuild backend-aws (runtime-check already passes; this would be unexpected).

---

## Files Modified

| File | Change |
|------|--------|
| `backend/app/core/runtime_identity.py` | New: `get_runtime_identity()`, `format_runtime_identity_short()` |
| `backend/app/services/telegram_commands.py` | Log `telegram_command_received` before dispatching /investigate |
| `backend/app/services/agent_telegram_commands.py` | Logs `runtime_identity`, `command_handler_selected`, `fallback_used`; `_get_investigate_debug_preamble()`; preamble in ack/error when `TELEGRAM_INVESTIGATE_DEBUG` |

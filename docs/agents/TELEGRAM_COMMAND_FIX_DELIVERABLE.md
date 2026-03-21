# Telegram Command Fix — Full Deliverable

**Date:** 2026-03-15  
**Status:** Fix implemented and deployed. Validation pending operator test.

---

## A. Root Cause Report

### What exactly was wrong

1. **Channel posts not requested** — `allowed_updates` in `get_telegram_updates()` did not include `channel_post` or `edited_channel_post`. In Telegram channels, admin posts appear as `channel_post`, not `message`. The bot never received these updates.

2. **Channel posts not handled** — `handle_telegram_update()` only read `message` and `edited_message`. It never checked `channel_post` or `edited_channel_post`.

3. **Auth mismatch** — Command authorization used `TELEGRAM_CHAT_ID` and `TELEGRAM_AUTH_USER_ID`. Alerts use `TELEGRAM_CHAT_ID_TRADING` (ATP Alerts). ATP Alerts was not in the command auth list, so even if updates were received, they would be denied.

4. **PENDING_VALUE_INPUTS** — Commands starting with `/` could be consumed by pending value input handlers before reaching command dispatch. Fixed by returning `False` for slash-commands in `_handle_pending_value_message()`.

### Where in code

| File | Location |
|------|----------|
| `backend/app/services/telegram_commands.py` | `get_telegram_updates()` — `allowed_updates` |
| `backend/app/services/telegram_commands.py` | `handle_telegram_update()` — message extraction |
| `backend/app/services/telegram_commands.py` | Startup — `AUTHORIZED_USER_IDS` (add `TELEGRAM_CHAT_ID_TRADING`) |
| `backend/app/services/telegram_commands.py` | `_handle_pending_value_message()` — skip commands |

### Why alerts worked but commands did not

- **Alerts:** Outbound only. `telegram_notifier` sends to `TELEGRAM_CHAT_ID_TRADING` using `sendMessage`. No polling or update handling. Works regardless of update types.
- **Commands:** Inbound only. Requires polling `getUpdates` with correct `allowed_updates` and handling the right update fields. Channel posts use `channel_post`, which was neither requested nor handled.

---

## B. Files Changed

| File | Change |
|------|--------|
| `backend/app/services/telegram_commands.py` | Added `channel_post`, `edited_channel_post` to `allowed_updates`; extract message from all four sources; add `TELEGRAM_CHAT_ID_TRADING` to `AUTHORIZED_USER_IDS`; skip commands in pending value handler; `_get_effective_bot_token()`; `[TG][INTAKE]`, `[TG][AUTH]`, `[TG][REPLY]` logs; try/except around handlers with error reply |
| `backend/app/services/agent_telegram_commands.py` | Updated help content with channel guidance |
| `backend/app/core/runtime_identity.py` | Created (runtime identity utilities) |
| `backend/app/services/agent_routing.py` | Created (agent routing) |
| `backend/scripts/diag/check_runtime_dependencies.py` | Created (runtime check script) |
| `docs/agents/AGENT_OPERATING_MODEL.md` | Created — channel responsibilities |
| `docs/agents/TELEGRAM_AGENT_COMMANDS.md` | Updated — command reference |
| `docs/agents/TELEGRAM_HILOVIVO3_COMMAND_DIAGNOSIS.md` | Created — root cause and fix |
| `docs/agents/TELEGRAM_INVESTIGATE_AGENT_FIX.md` | Created — fix summary |
| `docs/agents/multi-agent/ACCEPTANCE_CHECKLIST.md` | Updated — troubleshooting section |

---

## C. Fix Summary

### Behavior changes

1. **Intake:** Bot now requests and handles `channel_post` and `edited_channel_post`. Commands posted in HILOVIVO3.0 (a channel) are received.

2. **Auth:** `TELEGRAM_CHAT_ID_TRADING` is added to `AUTHORIZED_USER_IDS` at startup. ATP Alerts is authorized for commands.

3. **Reply:** All command handlers wrapped in try/except; failures send a visible error reply. No silent drops.

4. **Logging:** `[TG][INTAKE]`, `[TG][AUTH]`, `[TG][REPLY]` logs make the path traceable.

### Prerequisites for HILOVIVO3.0 commands

- Bot must be **admin** in the channel (required for receiving `channel_post`).
- `TELEGRAM_CHAT_ID_TRADING` must be set to ATP Alerts channel ID (e.g. `-1003820753438`).
- Same bot token used for alerts and commands (no token mismatch).

---

## D. Deployment Summary

- **Path:** Push to `main` triggers `Deploy to AWS EC2 (Session Manager)` workflow.
- **Commit:** `29d0a89` — fix(telegram): HILOVIVO3.0 command handling — channel_post + auth
- **Deploy steps:** Checkout → git pull on EC2 → clone frontend → render secrets → `docker compose --profile aws build --no-cache` → `docker compose --profile aws up -d`
- **Verification:** Check GitHub Actions for workflow success. On EC2: `docker compose --profile aws logs -n 100 backend-aws` for `[TG][CONFIG]` and `[TG][INTAKE]`.

---

## E. Validation Evidence Template

Run these tests **in HILOVIVO3.0** after deploy. Capture for each:

| Test | Command | Expected | Evidence |
|------|---------|----------|----------|
| 1 | `/help` | Reply with command list | ☐ |
| 2 | `/runtime-check` | Reply with runtime status | ☐ |
| 3 | `/investigate repeated BTC alerts` | Task received + agent selected | ☐ |
| 4 | `/agent sentinel investigate repeated BTC alerts` | Task received + Sentinel | ☐ |

**Log checks (backend-aws):**

- `[TG][INTAKE] update_source=channel_post chat_id=-100... chat_type=channel`
- `[TG][AUTH] ✅ Authorized` or `decision=ALLOW`
- `[TG][CMD] Routing /investigate` or `/runtime-check` or `/agent`
- No `[TG][DENY]` for these commands

---

## F. Final Operator Recommendation

### HILOVIVO3.0 can support command/reply

- **Yes.** With the fix, HILOVIVO3.0 (channel) can reliably support interactive commands.
- **Requirements:** Bot must be admin; `TELEGRAM_CHAT_ID_TRADING` set; deploy applied.

### Where to send commands

| Context | Use |
|---------|-----|
| **HILOVIVO3.0** | `/investigate`, `/agent`, `/runtime-check`, `/help` — main operator channel |
| **Claw** | OpenClaw-native: `/new`, `/reset`, `/status`, `/context` |
| **AWS_alerts** | Alerts only — no commands |
| **Direct bot chat** | Alternative if `TELEGRAM_AUTH_USER_ID` includes your user ID |

### If HILOVIVO3.0 still fails after deploy

1. Confirm bot is **admin** in the channel.
2. Confirm `TELEGRAM_CHAT_ID_TRADING` matches ATP Alerts channel ID.
3. Check logs for `[TG][DENY]` or missing `[TG][INTAKE]`.
4. Fallback: Use a **private supergroup** or **direct bot chat** for commands; keep HILOVIVO3.0 for alerts only.

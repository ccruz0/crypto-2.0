# Telegram Bot Report — Corrected & Mapped to Codebase

This document corrects and maps the external Telegram Bot Issues report to the actual codebase.

---

## A. Actual Code Paths (Update → Reply)

| Report Claim | Actual Codebase |
|--------------|-----------------|
| `telegram_config_loader.py` | Exists at `backend/app/config/telegram_config_loader.py`. Used by `scripts/diag/telegram_agent_interface_test.py` only. **Command handling does NOT use it.** |
| `telegram_commands.py` | `backend/app/services/telegram_commands.py` — main command handler. Uses `telegram_token_loader.get_telegram_token()` and `os.getenv("TELEGRAM_CHAT_ID")` directly, not `telegram_config_loader`. |
| `load_telegram_config()` | Used only in diag scripts. **Not used by production command flow.** |
| `send_message()` | `telegram_notifier.send_message()` — for alerts. Command replies use `send_command_response()` in `telegram_commands.py`. |
| `process_telegram_commands()` | Correct — in `telegram_commands.py`, called by scheduler every ~1s. |

**Command flow:** `scheduler` → `process_telegram_commands()` → `get_telegram_updates()` → handlers → `send_command_response()`.

---

## B. Proven Blockers — Corrected

### 1. Missing Environment Variables ✅ (Correct)

| Var | Where Used | Effect if Missing |
|-----|------------|------------------|
| `TELEGRAM_BOT_TOKEN` | `telegram_commands.py` (via `get_telegram_token()`), `telegram_notifier.py` | Commands and alerts fail. |
| `TELEGRAM_CHAT_ID` | `telegram_commands.py`, `telegram_notifier.py` | No target for messages. |
| `TELEGRAM_AUTH_USER_ID` | `telegram_commands.py` | Optional; falls back to `TELEGRAM_CHAT_ID`. |

**Token resolution order** (`telegram_token_loader.py`): `TELEGRAM_BOT_TOKEN` → `TELEGRAM_BOT_TOKEN_DEV` → interactive popup.

**AWS fallback** (`main.py`): `TELEGRAM_BOT_TOKEN_AWS` → `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID_AWS` → `TELEGRAM_CHAT_ID`.

### 2. Kill Switch — Corrected Semantics ⚠️

| Report Said | Actual Behavior |
|-------------|-----------------|
| "If kill switch is **enabled**, messages may be suppressed" | **Inverted.** When `tg_enabled_aws` = `"true"` → `kill_switch_enabled` = True → messages **allowed**. When `tg_enabled_aws` = `"false"` or missing → messages **blocked**. |

**Location:** `telegram_notifier._get_telegram_kill_switch_status()` reads DB `TradingSettings` for `tg_enabled_aws` (or `tg_enabled_local`).

**To allow messages on AWS:** Ensure `tg_enabled_aws` = `"true"` in DB.

### 3. RUN_TELEGRAM ✅ (Correct)

- `RUN_TELEGRAM=false` → Telegram disabled (startup check in `main.py`).
- Must be `true`/`1`/`yes`/`on` for Telegram to work.

### 4. Additional Blockers (Not in Original Report)

| Blocker | Location | Effect |
|---------|----------|--------|
| **Lock contention** | `telegram_commands.py` | Two pollers (backend + canary) → `Another poller is active`. **Fixed:** `RUN_TELEGRAM_POLLER=false` on canary. |
| **Dedup** | `telegram_update_dedup` table | Duplicate updates could cause routing issues. **Fixed:** migration + dedup in update processing. |
| **401 on startup** | `telegram_commands.py` | Invalid token → `_telegram_startup_401=True` → polling disabled. |

---

## C. Config Audit — Complete List

| Env Var | Purpose |
|---------|---------|
| `TELEGRAM_BOT_TOKEN` | Production bot token (AWS). |
| `TELEGRAM_BOT_TOKEN_DEV` | Dev bot token (local, avoids 409 with prod). |
| `TELEGRAM_CHAT_ID` | Primary control channel (ATP Control). |
| `TELEGRAM_CHAT_ID_TRADING` | Alerts-only (e.g. HILOVIVO3.0). |
| `TELEGRAM_AUTH_USER_ID` | Authorized chat/user IDs for commands (comma-separated). |
| `TELEGRAM_BOT_TOKEN_AWS` | AWS-specific token (fallback). |
| `TELEGRAM_CHAT_ID_AWS` | AWS-specific chat ID (fallback). |
| `RUN_TELEGRAM` | Master enable (true/false). |
| `RUN_TELEGRAM_POLLER` | Per-instance poller enable (canary = false). |

---

## D. Fix Plan — Aligned with Codebase

1. **Env vars:** Ensure `TELEGRAM_BOT_TOKEN` (or `TELEGRAM_BOT_TOKEN_AWS`) and `TELEGRAM_CHAT_ID` (or `TELEGRAM_CHAT_ID_AWS`) are set for AWS.
2. **Kill switch:** Ensure `tg_enabled_aws` = `"true"` in `TradingSettings` (enables Telegram, does not suppress).
3. **RUN_TELEGRAM:** Set to `true` for production.
4. **Canary:** `RUN_TELEGRAM_POLLER=false` on `backend-aws-canary` (already in `docker-compose.yml`).
5. **Logging:** `[TG]`-prefixed logs already exist; use `grep TG` on backend logs for diagnostics.

---

## E. Verification Commands

```bash
# On EC2 (via SSM)
docker compose --profile aws logs backend-aws 2>&1 | grep TG | tail -30
```

**ATP Control:** Send `/start`, `/help`, `/runtime-check` — should receive replies.

---

## F. Summary of Corrections (Final)

| Original Claim | Actual Behavior |
|----------------|-----------------|
| `telegram_config_loader` is central | Used only by diagnostic scripts. Commands use `telegram_token_loader` and env vars directly. |
| Kill switch **enabled** suppresses messages | Inverted: `tg_enabled_aws = "true"` **allows** messages; `"false"` or missing **blocks** them. |
| `load_telegram_config()` drives commands | Not used in command path; `telegram_commands.py` uses `get_telegram_token()` and `os.getenv()`. |

### Accurate Blockers

1. **Missing env vars:** `TELEGRAM_BOT_TOKEN` or `TELEGRAM_CHAT_ID` missing → no messages.
2. **RUN_TELEGRAM:** Set to `"false"` **to** disable Telegram.
3. **Database:** `tg_enabled_aws` must be `"true"` in `TradingSettings` for AWS to allow messages.

### Additional Blockers

1. **Lock contention:** Two pollers → mitigated by `RUN_TELEGRAM_POLLER=false` on canary.
2. **401 on startup:** Invalid token → `_telegram_startup_401=True` → polling disabled.

### Fix Plan

1. Set `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` (or `*_AWS` variants).
2. Set `tg_enabled_aws = "true"` in DB (`TradingSettings`).
3. Set `RUN_TELEGRAM = "true"`.
4. Keep `RUN_TELEGRAM_POLLER=false` on canary.

---

## G. Verification Scripts

| Script | Purpose |
|--------|---------|
| `./scripts/verify_telegram_config_aws.sh` | SSM: Check tg_enabled, RUN_TELEGRAM, RUN_TELEGRAM_POLLER on EC2. |
| `python backend/scripts/diag/verify_telegram_tg_enabled.py` | Local/container: Check tg_enabled_aws in DB. |
| `python backend/scripts/diag/verify_telegram_tg_enabled.py --set-true` | Set tg_enabled_aws to `"true"` if missing/false. |

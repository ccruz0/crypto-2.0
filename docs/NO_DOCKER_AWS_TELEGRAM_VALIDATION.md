## No-Docker AWS validation runbook (Telegram state consistency)

### Preconditions

- You have SSH access to the AWS instance running the backend via systemd.
- The backend service loads an env that includes **`ENVIRONMENT=aws`**, **`RUN_TELEGRAM=true`** and the Telegram variables.

### 1) Identify the backend systemd service

Run:

```bash
systemctl list-units --type=service --all | grep -Ei "crypto|trading|uvicorn|fastapi|atp"
```

Expected:

- One or more matching services (example names): `atp-backend.service`, `backend.service`, `uvicorn.service`, etc.

### 2) Confirm environment is loaded by systemd

Run:

```bash
systemctl show <service> -p Environment
systemctl show <service> -p EnvironmentFile
```

Expected:

- `Environment=` includes **`ENVIRONMENT=aws`** and **`RUN_TELEGRAM=true`**
- Telegram credentials are present via either:
  - **Preferred**: `TELEGRAM_BOT_TOKEN_AWS` and `TELEGRAM_CHAT_ID_AWS`
  - **Fallback**: `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID`

### 3) Restart and tail the relevant logs

Run:

```bash
sudo systemctl restart <service>
journalctl -u <service> -n 300 --no-pager | grep -E "TELEGRAM_RUNTIME|TG BLOCKED|GLOBAL_BLOCKER|SIGNAL_EVAL"
```

Expected after this fix:

- At least one per-cycle line like:
  - `[TELEGRAM_RUNTIME] ... enabled=True chat_id=<id> reasons=`
- No false blocker like:
  - `[GLOBAL_BLOCKER] Telegram notifier is disabled ...` **while Telegram is actually configured and sending**
- If Telegram *is* blocked, you see:
  - `[TG BLOCKED] ... reasons=run_telegram_disabled,kill_switch_disabled,token_missing,chat_id_missing,...`
  - The reasons match the actual guard being used at runtime.

### 4) Host-Python verification (no Docker)

Run (adjust repo path if needed):

```bash
cd /home/ubuntu/automated-trading-platform/backend && /usr/bin/python3 - <<'PY'
from app.services.telegram_notifier import TelegramNotifier

notifier = TelegramNotifier()
cfg = notifier.refresh_config()
print("refresh_config():", cfg)

# Sends a real Telegram message if enabled=True.
ok = notifier.send_message("[TG CONFIG CHECK] refresh_config() says enabled=%s chat_id=%s reasons=%s" % (
    cfg.get("enabled"),
    cfg.get("chat_id"),
    cfg.get("block_reasons"),
), origin="AWS")
print("send_message() ok:", ok)
PY
```

Expected:

- The printed `refresh_config()` dict matches what you see in `[TELEGRAM_RUNTIME]`.
- If `enabled=True`, `send_message() ok: True` and a Telegram message arrives.
- If `enabled=False`, `send_message() ok: False` and logs include `[TG BLOCKED] ... reasons=...`.


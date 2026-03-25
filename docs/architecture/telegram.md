# Telegram architecture (PRODUCTION ONLY)

## Ownership

- **Production (AWS)** owns all live Telegram behavior: command polling, `/task`, callbacks, and the operational contract with users.
- **LAB / local / OpenClaw** must **not** run a Telegram poller and must **not** hold or use production bot tokens for polling or command handling.

Compose and `secrets/runtime.env` are the primary enforcement layer; the backend also applies a LAB runtime guard in code (see `process_telegram_commands`).

## Single poller rule

Exactly **one** process in production may call Telegram `getUpdates` for the ATP Control bot:

| Service | Profile | `RUN_TELEGRAM_POLLER` | Role |
|--------|---------|----------------------|------|
| **backend-aws** | `aws` | `true` | **Only** allowed poller |
| backend-aws-canary | `aws` | `false` | Same image; must not poll |
| backend / backend-dev | `local` | forced `false` | LAB — no Telegram |
| openclaw | openclaw compose | forced `false` | LAB — no Telegram |

**Debugging rule:** If commands or callbacks misbehave, **check pollers first** (duplicate `getUpdates` → HTTP 409 / "another poller" symptoms).

## Tokens

### Canonical polling token (production)

- **`TELEGRAM_ATP_CONTROL_BOT_TOKEN`** — **single canonical env var for polling** on AWS (`backend-aws`).
- On AWS, `get_telegram_token()` uses **only** this variable for the poller path (no fallback to `TELEGRAM_BOT_TOKEN` for polling).

### Outbound / alerts token (production, not polling)

- **`TELEGRAM_BOT_TOKEN`** — **kept for compatibility**: trading and alert **outbound** sends (`telegram_notifier`, market-updater paths) that target the alerts/trading bot.
- It is **not** the polling token on AWS; do not remove it from production unless you migrate every outbound send path to another mechanism.

Rotation for production should keep **both** `TELEGRAM_ATP_CONTROL_BOT_TOKEN` and `TELEGRAM_BOT_TOKEN` aligned with your secrets process where both bots share the same token or where ops updates both (see admin/SSM refresh path and runbooks).

### LAB

- Do not set production values for `TELEGRAM_ATP_CONTROL_BOT_TOKEN`, `TELEGRAM_BOT_TOKEN`, or `TELEGRAM_BOT_TOKEN_AWS` on LAB services.
- Compose forces these empty where `secrets/runtime.env` might otherwise mirror prod.

## Related documentation

- Duplicate poller incident: `docs/runbooks/telegram_duplicate_poller_incident.md`
- Env template: `secrets/runtime.env.example` (Telegram block)

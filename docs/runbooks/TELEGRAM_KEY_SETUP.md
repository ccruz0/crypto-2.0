# Telegram key setup (for local Notion pickup + approval)

So that the Notion task pickup script can send approval messages to Telegram when run **locally**, the backend must have a Telegram bot token. The token can be provided in two ways.

## Option A: Use the same key as the server (decrypt existing token)

If you have the **same** `secrets/telegram_key` file that the server uses (it was used to create `TELEGRAM_BOT_TOKEN_ENCRYPTED` in `secrets/runtime.env`):

1. Copy it from the server to your repo (never commit it):
   ```bash
   scp user@your-ec2:/home/ubuntu/automated-trading-platform/secrets/telegram_key ./secrets/telegram_key
   chmod 600 secrets/telegram_key
   ```
2. Ensure `secrets/runtime.env` is present and contains `TELEGRAM_BOT_TOKEN_ENCRYPTED` and `TELEGRAM_CHAT_ID` (it already does if you pulled from server config).
3. Run the pickup script from repo root; it will set `TELEGRAM_KEY_FILE=secrets/telegram_key` and the backend will decrypt the token.

No other setup needed. `backend/.env` should have `TELEGRAM_CHAT_ID=839853931` (or your channel ID) for the approval target.

## Option B: Create a new key and encrypt your token locally

If you **don’t** have `secrets/telegram_key` from the server, create a local key and store the token encrypted in `backend/.env`:

1. From the **repo root**:
   ```bash
   TELEGRAM_ENV_FILE=backend/.env python3 scripts/setup_telegram_token.py
   ```
2. When the popup appears, paste your Telegram bot token (from [@BotFather](https://t.me/BotFather)).
3. The script will:
   - Create **`.telegram_key`** in the repo root (32-byte key; keep it secret, it’s in `.gitignore`).
   - Write **`TELEGRAM_BOT_TOKEN_ENCRYPTED`** to **`backend/.env`** (encrypted with that key).
4. Ensure **`backend/.env`** also has **`TELEGRAM_CHAT_ID`** (e.g. `TELEGRAM_CHAT_ID=839853931`). Add it if missing.
5. Run the pickup script; it will set `TELEGRAM_KEY_FILE` to `.telegram_key` and load `backend/.env` (which overrides `secrets/runtime.env` for the encrypted token), so the backend can decrypt and send.

**Note:** With Option B, the encrypted value in `backend/.env` is different from the one on the server (different key). Use Option B only for local use; don’t copy this `backend/.env` or `.telegram_key` to the server.

## Verify

After either option, run one pickup cycle with the task in **Planned**:

```bash
NOTION_TASK_DB=eb90cfa139f94724a8b476315908510a ./scripts/run_notion_task_pickup.sh
```

You should see the approval message in Telegram (no “missing TELEGRAM_BOT_TOKEN or chat_id” in the logs).

## Where the key and token live

| Item | Location (local) | Location (server) |
|------|-------------------|-------------------|
| **Decryption key** | `secrets/telegram_key` or `.telegram_key` (repo root) | `secrets/telegram_key` |
| **Encrypted token** | `backend/.env` (Option B) or `secrets/runtime.env` (Option A) | `secrets/runtime.env` |
| **Chat ID** | `backend/.env` | `secrets/runtime.env` |

See also [secrets_runtime_env.md](secrets_runtime_env.md) and [REAL_ADDRESSES.md](REAL_ADDRESSES.md).

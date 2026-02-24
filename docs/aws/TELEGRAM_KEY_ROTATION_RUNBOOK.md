# Telegram key rotation runbook

Use this runbook to rotate the Telegram token encryption key (e.g. quarterly). The key is stored in `secrets/telegram_key` on EC2 and in `.telegram_key` locally. Rotating the key invalidates the current `TELEGRAM_BOT_TOKEN_ENCRYPTED` value until you re-encrypt the same (or a new) token with the new key.

**Principle:** Never expose the plaintext bot token. Re-encrypt using `scripts/setup_telegram_token.py` in a secure environment, then deploy only the new encrypted value and new key file.

---

## When to rotate

- Quarterly (recommended).
- After any suspicion of key or token compromise.
- After team member with access to the key leaves.

---

## Prerequisites

- Local (or secure) machine with repo clone.
- Access to BotFather to get the current (or a new) bot token if you are also rotating the token.
- Access to EC2 (or deployment target) to update `secrets/telegram_key` and `.env.aws` / SSM.

---

## Option A: Rotate key only (same bot token)

Use when you want a new encryption key but keep the same Telegram bot token.

### 1) On a secure machine (e.g. your laptop)

```bash
cd /path/to/repo   # e.g. ~/automated-trading-platform or ~/crypto-2.0

# Backup current key and env (do not commit)
cp .telegram_key .telegram_key.bak 2>/dev/null || true
cp .env .env.bak 2>/dev/null || true

# Decrypt current token once so we can re-encrypt with new key.
# Run setup script: it will prompt for the token. Paste the SAME token from BotFather (or from your password manager).
python3 scripts/setup_telegram_token.py
# When prompted, paste the existing bot token. Script writes new .telegram_key and TELEGRAM_BOT_TOKEN_ENCRYPTED to .env.
```

### 2) Copy only the new key and encrypted value to EC2

- Copy the **new** `.telegram_key` to the instance as `secrets/telegram_key` (overwrite).
- Update `.env.aws` (or SSM) with the **new** `TELEGRAM_BOT_TOKEN_ENCRYPTED` value from `.env`. Do **not** copy any line that sets the plaintext TELEGRAM_BOT_TOKEN.

Use a secure channel (e.g. SSM Parameter Store, or scp with restricted keys). Never paste the plaintext token or the raw key into chat or email.

### 3) On EC2

```bash
cd ~/crypto-2.0

# Replace secrets/telegram_key with the new key file you copied
chmod 600 secrets/telegram_key
chown ubuntu:ubuntu secrets/telegram_key

# If you use .env.aws (not SSM), update TELEGRAM_BOT_TOKEN_ENCRYPTED there, then:
bash scripts/aws/render_runtime_env.sh
docker compose --profile aws up -d

# Verify
docker compose --profile aws ps
curl -sS http://127.0.0.1:8002/health
python3 scripts/send_telegram_test_minimal.py
```

### 4) Clean up

- Securely delete `.telegram_key.bak` and `.env.bak` on the secure machine after confirming production works.
- Revoke or overwrite any old key backups.

---

## Option B: Rotate both key and bot token

Use when the token was compromised or you want a new bot.

1. In BotFather: revoke the old token and create a new one.
2. On a secure machine, run `python3 scripts/setup_telegram_token.py` and paste the **new** token. This creates a new key and `TELEGRAM_BOT_TOKEN_ENCRYPTED`.
3. Deploy the new key and new `TELEGRAM_BOT_TOKEN_ENCRYPTED` to EC2 as in Option A steps 2–4.
4. Update any other consumers (e.g. Alertmanager/telegram-alerts) with the new token if they use the same bot.

---

## Rollback

If something goes wrong after key rotation:

- Restore the previous `secrets/telegram_key` and previous `TELEGRAM_BOT_TOKEN_ENCRYPTED` (from backup or SSM/.env.aws backup).
- Run `bash scripts/aws/render_runtime_env.sh` and `docker compose --profile aws up -d`.
- Then fix the rotation procedure and retry.

---

## Checklist

- [ ] Backup current `.telegram_key` and `TELEGRAM_BOT_TOKEN_ENCRYPTED` (secure, ephemeral).
- [ ] Run `scripts/setup_telegram_token.py` with same or new token; get new key and encrypted value.
- [ ] Deploy only new key file and new `TELEGRAM_BOT_TOKEN_ENCRYPTED` to EC2 (no plaintext).
- [ ] On EC2: `chmod 600 secrets/telegram_key`, render runtime.env, restart stack.
- [ ] Verify health and send test Telegram message.
- [ ] Securely delete old key and old encrypted value backups.

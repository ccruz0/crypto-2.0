# OpenClaw Telegram — Restore / Fix

When OpenClaw stops replying on Telegram, follow these steps.

## /investigate pydantic_settings error

If `/investigate repeated BTC alerts` (or similar) fails with `ModuleNotFoundError: pydantic_settings`, **OpenClaw** is receiving the command and running ATP Python code from the mounted workspace. The ATP bot (backend-aws) has pydantic-settings and passes runtime-check; the mismatch means you are messaging the Claw bot, not the ATP bot. See [INVESTIGATE_EXECUTION_PATH.md](../agents/INVESTIGATE_EXECUTION_PATH.md) for the full execution path and diagnostics.

**Fix:** Use the ATP wrapper image (which adds pydantic/pydantic-settings) and redeploy:

```bash
# From your Mac (builds for linux/amd64, pushes to GHCR, deploys on LAB):
./scripts/openclaw/deploy_openclaw_lab_from_mac.sh
```

Or build and push manually:

```bash
docker build --platform linux/amd64 -f openclaw/Dockerfile.openclaw -t openclaw-with-origins:latest .
docker tag openclaw-with-origins:latest ghcr.io/ccruz0/openclaw:latest
docker push ghcr.io/ccruz0/openclaw:latest
# Then on LAB: docker pull ghcr.io/ccruz0/openclaw:latest && restart openclaw
```

## What was done (2026-03-13)

1. **Cheap-first model** — Set `primary` to `openai/gpt-4o-mini` (uses OpenAI credits first), Anthropic as fallback.

2. **Added `channels.telegram` to openclaw.json** on LAB:
   - `enabled: true`
   - `dmPolicy: pairing` (requires pairing approval for first DM)

2. **Ensured `TELEGRAM_BOT_TOKEN`** in LAB's `secrets/runtime.env`:
   - Run `bash scripts/aws/render_runtime_env.sh` on LAB (requires SSM params or .env.aws)
   - Or add manually: `TELEGRAM_BOT_TOKEN=your_token_from_botfather`

3. **Restarted OpenClaw** so it picks up the new config and env.

## If Telegram still doesn't work

### 1. Pairing (if using dmPolicy: pairing)

1. DM your Claw bot in Telegram.
2. On LAB, run:
   ```bash
   docker exec openclaw openclaw pairing list telegram
   docker exec openclaw openclaw pairing approve telegram <CODE>
   ```
   Pairing codes expire after 1 hour.

### 2. Use allowlist instead of pairing

Edit `/opt/openclaw/home-data/openclaw.json` on LAB:

```json
{
  "channels": {
    "telegram": {
      "enabled": true,
      "dmPolicy": "allowlist",
      "allowFrom": ["YOUR_TELEGRAM_USER_ID"]
    }
  }
}
```

To get your Telegram user ID: DM your bot, then `curl "https://api.telegram.org/bot<TOKEN>/getUpdates"` and look for `from.id`.

### 3. Verify token and config

```bash
# On LAB (via SSM or SSH):
docker exec openclaw printenv TELEGRAM_BOT_TOKEN | head -c 10 && echo "..."
cat /opt/openclaw/home-data/openclaw.json | grep -A5 telegram
docker logs openclaw --tail 50 | grep -i telegram
```

### 4. Re-run the enable script

```bash
# From your Mac:
./scripts/openclaw/enable_openclaw_telegram_via_ssm.sh
```

Or on LAB:
```bash
cd /home/ubuntu/automated-trading-platform
sudo bash scripts/openclaw/enable_openclaw_telegram.sh
```

## Disable Telegram (409 / duplicate poller vs PROD)

If PROD `backend-aws` polls `TELEGRAM_ATP_CONTROL_BOT_TOKEN` for @ATP_control_bot, OpenClaw must **not** use that same token (polling or webhook). Symptoms: backend logs `Another poller is active`, HTTP 409 on `getUpdates`, `/task` still creates Notion rows but Telegram also shows OpenClaw/read-only replies or duplicate “Unknown command”.

1. **Pull latest** on LAB so `docker-compose.openclaw.yml` strips `TELEGRAM_*` inside the OpenClaw container.
2. **Disable channel in config and restart:**
   ```bash
   # From Mac:
   ./scripts/openclaw/disable_openclaw_telegram_via_ssm.sh
   ```
   Or on LAB: `sudo bash scripts/openclaw/disable_openclaw_telegram.sh`
3. **Verify:** `docker exec openclaw printenv TELEGRAM_BOT_TOKEN | wc -c` (should be ~1: newline only). `docker logs openclaw --tail 50` should not show Telegram polling errors.

To use Telegram with OpenClaw again, use a **different** BotFather bot than PROD ATP Control; see warnings in `enable_openclaw_telegram.sh`.

## Scripts

| Script | Purpose |
|--------|---------|
| `scripts/openclaw/enable_openclaw_telegram.sh` | Run on LAB: add Telegram config, ensure token, restart |
| `scripts/openclaw/enable_openclaw_telegram_via_ssm.sh` | Run from Mac: invokes enable script on LAB via SSM |
| `scripts/openclaw/disable_openclaw_telegram.sh` | Run on LAB: disable `channels.telegram`, restart OpenClaw |
| `scripts/openclaw/disable_openclaw_telegram_via_ssm.sh` | Run from Mac: disable Telegram on LAB via SSM |
| `scripts/openclaw/merge_telegram_config.py` | Python helper to merge channels.telegram into config |

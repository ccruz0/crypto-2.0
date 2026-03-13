#!/usr/bin/env bash
# Enable OpenClaw Telegram channel on LAB.
# 1. Adds channels.telegram to openclaw.json (enabled, dmPolicy: pairing)
# 2. Ensures TELEGRAM_BOT_TOKEN is in secrets/runtime.env (from SSM or existing)
# 3. Restarts OpenClaw container
#
# Run on LAB (via SSM or SSH). From Mac: use enable_openclaw_telegram_via_ssm.sh

set -e

REPO="${REPO:-/home/ubuntu/automated-trading-platform}"
CONFIG_PATH="${OPENCLAW_CONFIG_PATH:-/opt/openclaw/home-data/openclaw.json}"
RUNTIME_ENV="${REPO}/secrets/runtime.env"
SSM_BOT_TOKEN="/automated-trading-platform/prod/telegram/bot_token"

echo "=== 1) Ensure TELEGRAM_BOT_TOKEN in secrets/runtime.env ==="
mkdir -p "$(dirname "$RUNTIME_ENV")"
touch "$RUNTIME_ENV"

if grep -q "^TELEGRAM_BOT_TOKEN=" "$RUNTIME_ENV" 2>/dev/null && [[ -n "$(grep "^TELEGRAM_BOT_TOKEN=" "$RUNTIME_ENV" | cut -d= -f2)" ]]; then
  echo "TELEGRAM_BOT_TOKEN already set in runtime.env"
else
  echo "Fetching TELEGRAM_BOT_TOKEN from SSM..."
  TOKEN=""
  if command -v aws >/dev/null 2>&1; then
    TOKEN=$(aws ssm get-parameter --name "$SSM_BOT_TOKEN" --with-decryption --query "Parameter.Value" --output text 2>/dev/null || true)
  fi
  if [[ -n "$TOKEN" ]]; then
    grep -v "^TELEGRAM_BOT_TOKEN=" "$RUNTIME_ENV" 2>/dev/null > "${RUNTIME_ENV}.tmp" || true
    echo "TELEGRAM_BOT_TOKEN=$TOKEN" >> "${RUNTIME_ENV}.tmp"
    mv "${RUNTIME_ENV}.tmp" "$RUNTIME_ENV"
    echo "Added TELEGRAM_BOT_TOKEN from SSM"
  else
    echo "WARNING: Could not get TELEGRAM_BOT_TOKEN from SSM. Add it manually to $RUNTIME_ENV"
    echo "  Example: TELEGRAM_BOT_TOKEN=<your_token_from_botfather>"
  fi
fi

echo ""
echo "=== 2) Add channels.telegram to OpenClaw config ==="
mkdir -p "$(dirname "$CONFIG_PATH")"
chown 1000:1000 "$(dirname "$CONFIG_PATH")" 2>/dev/null || true
export OPENCLAW_CONFIG_PATH="$CONFIG_PATH"

python3 << 'PYEOF'
import json
import os

path = os.environ.get("OPENCLAW_CONFIG_PATH", "/opt/openclaw/home-data/openclaw.json")
cfg = {}
if os.path.exists(path):
    with open(path) as f:
        cfg = json.load(f)

channels = cfg.setdefault("channels", {})
tg = channels.setdefault("telegram", {})
tg["enabled"] = True
tg["dmPolicy"] = tg.get("dmPolicy", "pairing")
# botToken from env (TELEGRAM_BOT_TOKEN) if not in config
if "botToken" not in tg or not tg["botToken"]:
    tg.pop("botToken", None)  # Let OpenClaw use env fallback

# Cheap-first: OpenAI gpt-4o-mini primary (has credits), Anthropic as fallback
agents = cfg.setdefault("agents", {}).setdefault("defaults", {}).setdefault("model", {})
agents["primary"] = "openai/gpt-4o-mini"
fb = agents.get("fallbacks", [])
openai_fb = [x for x in fb if "openai" in x.lower()]
anthropic_fb = [x for x in fb if "anthropic" in x.lower()]
agents["fallbacks"] = openai_fb + anthropic_fb if (openai_fb or anthropic_fb) else fb

with open(path, "w") as f:
    json.dump(cfg, f, indent=2)

print("Updated config at", path)
print("channels.telegram:", json.dumps(tg, indent=2))
PYEOF

echo ""
echo "=== 3) Restart OpenClaw ==="
cd "$REPO"
if docker ps -q -f name=openclaw 2>/dev/null | grep -q .; then
  docker compose -f docker-compose.openclaw.yml restart openclaw 2>/dev/null || \
  docker restart openclaw 2>/dev/null || true
  echo "Restarted OpenClaw"
else
  docker compose -f docker-compose.openclaw.yml up -d 2>/dev/null || true
  echo "Started OpenClaw"
fi

echo ""
echo "=== 4) Verify ==="
sleep 5
docker logs openclaw --tail 20 2>&1 | grep -iE "telegram|error|started" || docker logs openclaw --tail 10 2>&1

echo ""
echo "=== Done ==="
echo "If using pairing: DM your Claw bot, run 'openclaw pairing list telegram' and 'openclaw pairing approve telegram <CODE>'"
echo "Or set dmPolicy: allowlist with your Telegram user ID in allowFrom."

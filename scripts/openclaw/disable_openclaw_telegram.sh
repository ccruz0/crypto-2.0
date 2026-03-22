#!/usr/bin/env bash
# Disable OpenClaw Telegram channel on LAB (no getUpdates / webhook for bot token).
# Run on LAB after git pull. Use when backend-aws polls TELEGRAM_ATP_CONTROL_BOT_TOKEN on PROD
# to eliminate duplicate consumers (409 conflict, stray OpenClaw replies, "Unknown command").
#
# Usage (LAB): sudo bash scripts/openclaw/disable_openclaw_telegram.sh
# From Mac:    ./scripts/openclaw/disable_openclaw_telegram_via_ssm.sh

set -euo pipefail

REPO="${REPO:-/home/ubuntu/automated-trading-platform}"
CONFIG_PATH="${OPENCLAW_CONFIG_PATH:-/opt/openclaw/home-data/openclaw.json}"

echo "=== Disable OpenClaw Telegram (LAB) ==="
echo "Config: $CONFIG_PATH"

mkdir -p "$(dirname "$CONFIG_PATH")"
touch "$CONFIG_PATH"
chown 1000:1000 "$CONFIG_PATH" 2>/dev/null || true

export OPENCLAW_CONFIG_PATH="$CONFIG_PATH"
python3 << 'PYEOF'
import json
import os

path = os.environ.get("OPENCLAW_CONFIG_PATH", "/opt/openclaw/home-data/openclaw.json")
cfg = {}
if os.path.exists(path) and os.path.getsize(path) > 0:
    with open(path) as f:
        cfg = json.load(f)

channels = cfg.setdefault("channels", {})
tg = channels.setdefault("telegram", {})
tg["enabled"] = False
# Remove inline token so a future env leak does not re-enable implicitly
if "botToken" in tg:
    tg.pop("botToken", None)

with open(path, "w") as f:
    json.dump(cfg, f, indent=2)

print("Updated", path)
print("channels.telegram:", json.dumps(tg, indent=2))
PYEOF

cd "$REPO"
if docker ps -q -f name=openclaw 2>/dev/null | grep -q .; then
  # restart does not apply new compose `environment:` overrides; must recreate
  docker compose -f docker-compose.openclaw.yml up -d --force-recreate --no-deps openclaw 2>/dev/null || \
  docker compose -f docker-compose.openclaw.yml up -d --no-deps openclaw 2>/dev/null || \
  docker restart openclaw 2>/dev/null || true
  echo "Recreated OpenClaw (compose clears TELEGRAM_* from env_file)."
else
  echo "OpenClaw container not running; config updated for next start."
fi

echo ""
echo "=== Done ==="
echo "Verify: docker exec openclaw printenv TELEGRAM_BOT_TOKEN | wc -c   # expect 0 or 1 (newline only)"
echo "         docker logs openclaw --tail 30 | grep -iE '409|telegram|getUpdates' || true"

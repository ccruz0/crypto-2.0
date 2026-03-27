#!/usr/bin/env bash
# Capture ATP Control Alerts channel ID via getUpdates.
# Run on EC2 (or where backend runs). You must send /menu in the ATP Control Alerts
# channel DURING the capture window.
#
# Usage: ./scripts/capture_atp_control_channel_id.sh
# Or via SSM: aws ssm send-command --instance-ids i-087953603011543c5 \
#   --document-name AWS-RunShellScript \
#   --parameters 'commands=["cd /home/ubuntu/crypto-2.0 && ./scripts/capture_atp_control_channel_id.sh"]'

set -e
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO"

# Load token
for f in secrets/runtime.env .env.aws; do
  if [[ -f "$f" ]]; then
    set +u
    # shellcheck source=/dev/null
    source "$f" 2>/dev/null || true
    set -u
  fi
done
TOKEN="${TELEGRAM_BOT_TOKEN:-$TELEGRAM_ATP_CONTROL_BOT_TOKEN}"
if [[ -z "$TOKEN" ]]; then
  echo "ERROR: TELEGRAM_BOT_TOKEN not found in secrets/runtime.env or .env.aws" >&2
  exit 1
fi

echo "=============================================="
echo "SEND /menu IN ATP CONTROL ALERTS CHANNEL NOW"
echo "You have 25 seconds..."
echo "=============================================="

docker stop automated-trading-platform-backend-aws-1 2>/dev/null || true
sleep 25

echo "Fetching getUpdates..."
curl -s "https://api.telegram.org/bot${TOKEN}/getUpdates?limit=50" -o /tmp/tg_capture.json

echo "Starting backend..."
docker start automated-trading-platform-backend-aws-1 2>/dev/null || true

# Extract channel IDs
python3 << 'PY'
import json
try:
    with open("/tmp/tg_capture.json") as f:
        d = json.load(f)
    for u in d.get("result", []):
        m = u.get("channel_post") or u.get("message", {})
        c = m.get("chat", {})
        cid = c.get("id")
        if cid and (c.get("type") == "channel" or (isinstance(cid, int) and cid < 0)):
            print(f"CHANNEL_ID={cid}")
            print(f"CHANNEL_TITLE={c.get('title', '')[:50]}")
            exit(0)
    print("NO_CHANNEL_FOUND")
except Exception as e:
    print(f"ERROR: {e}")
PY

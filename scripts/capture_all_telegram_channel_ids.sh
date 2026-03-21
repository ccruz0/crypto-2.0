#!/usr/bin/env bash
# Capture channel IDs for all configured Telegram bots via getUpdates.
# Send a message (e.g. /menu or any text) in EACH channel DURING the capture window.
#
# Usage: ./scripts/capture_all_telegram_channel_ids.sh
#
# Output: TELEGRAM_*_CHAT_ID values to add to secrets/runtime.env
set -e
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO"

# Load env
for f in .env .env.aws secrets/runtime.env; do
  [[ -f "$f" ]] && set -a && source "$f" 2>/dev/null || true && set +a
done

echo "=============================================="
echo "SEND A MESSAGE IN EACH CHANNEL NOW:"
echo "  1. ATP Control Alerts"
echo "  2. AWS_alerts"
echo "  3. Claw"
echo "  4. HILOVIVO3.0"
echo "You have 45 seconds..."
echo "=============================================="
sleep 45

python3 << 'PY'
import os
import json
import urllib.request

# Map channel title keywords to env var
TITLE_TO_VAR = {
    "ATP Control": "TELEGRAM_ATP_CONTROL_CHAT_ID",
    "ATP Control Alerts": "TELEGRAM_ATP_CONTROL_CHAT_ID",
    "AWS": "TELEGRAM_ALERT_CHAT_ID",
    "AWS_alerts": "TELEGRAM_ALERT_CHAT_ID",
    "Claw": "TELEGRAM_CLAW_CHAT_ID",
    "HILOVIVO": "TELEGRAM_CHAT_ID_TRADING",
    "HiloVivo": "TELEGRAM_CHAT_ID_TRADING",
    "ATP Alerts": "TELEGRAM_CHAT_ID_TRADING",
}

def env_var_for_title(title):
    t = (title or "").upper()
    for kw, var in TITLE_TO_VAR.items():
        if kw.upper() in t:
            return var
    return None

tokens = [
    ("TELEGRAM_ATP_CONTROL_BOT_TOKEN", os.environ.get("TELEGRAM_ATP_CONTROL_BOT_TOKEN") or os.environ.get("TELEGRAM_CLAW_BOT_TOKEN")),
    ("TELEGRAM_ALERT_BOT_TOKEN", os.environ.get("TELEGRAM_ALERT_BOT_TOKEN") or os.environ.get("TELEGRAM_BOT_TOKEN")),
    ("TELEGRAM_CLAW_BOT_TOKEN", os.environ.get("TELEGRAM_CLAW_BOT_TOKEN") or os.environ.get("TELEGRAM_BOT_TOKEN")),
    ("TELEGRAM_BOT_TOKEN", os.environ.get("TELEGRAM_BOT_TOKEN")),
]

seen_cids = {}
for var, token in tokens:
    if not token:
        continue
    try:
        url = f"https://api.telegram.org/bot{token}/getUpdates?limit=100"
        with urllib.request.urlopen(url, timeout=10) as r:
            d = json.loads(r.read().decode())
        for u in d.get("result", []):
            m = u.get("channel_post") or u.get("message", {})
            c = m.get("chat", {})
            cid = c.get("id")
            if cid and (c.get("type") == "channel" or (isinstance(cid, int) and cid < 0)):
                title = (c.get("title") or c.get("username") or "").strip()
                if cid not in seen_cids:
                    env_var = env_var_for_title(title) or "TELEGRAM_*_CHAT_ID"
                    seen_cids[cid] = (title[:50], env_var)
    except Exception as e:
        print(f"# {var}: ERROR {e}")

print("# Add these to secrets/runtime.env (map by channel title):\n")
for cid, (title, env_var) in sorted(seen_cids.items(), key=lambda x: x[0]):
    print(f"# {title or '(no title)'}")
    if env_var != "TELEGRAM_*_CHAT_ID":
        print(f"{env_var}={cid}")
    else:
        print(f"# TELEGRAM_*_CHAT_ID={cid}  # map to correct var")
    print()
PY

echo "Add the lines above to secrets/runtime.env (or .env.aws on EC2)."
echo "Run: python scripts/verify_telegram_destinations.py to confirm distinct destinations."

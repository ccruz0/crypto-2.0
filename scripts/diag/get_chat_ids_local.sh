#!/usr/bin/env bash
# Get Telegram chat IDs locally. No pip/requests needed.
# Token from: .env.aws, secrets/runtime.env, or TELEGRAM_BOT_TOKEN env var.
#
# Usage:
#   cd ~/automated-trading-platform && ./scripts/diag/get_chat_ids_local.sh
#   TELEGRAM_BOT_TOKEN=xxx ./scripts/diag/get_chat_ids_local.sh

set -e

REPO="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$REPO"

# Load token from env files
for f in secrets/runtime.env .env.aws .env; do
  if [ -f "$f" ]; then
    set +u
    # shellcheck source=/dev/null
    . "$f" 2>/dev/null || true
    set -u
  fi
done

TOKEN="${TELEGRAM_BOT_TOKEN:-$TELEGRAM_BOT_TOKEN_AWS}"
if [ -z "$TOKEN" ]; then
  echo "TELEGRAM_BOT_TOKEN not found. Set it or add to .env.aws / secrets/runtime.env"
  echo ""
  echo "Example: TELEGRAM_BOT_TOKEN=123456:ABC ./scripts/diag/get_chat_ids_local.sh"
  exit 1
fi

echo "Checking getWebhookInfo..."
WH=$(curl -s "https://api.telegram.org/bot${TOKEN}/getWebhookInfo")
WH_URL=$(echo "$WH" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('result',{}).get('url','') or '')" 2>/dev/null)
if [ -n "$WH_URL" ]; then
  echo "⚠️  Webhook active at: $WH_URL"
  echo "   getUpdates returns empty while webhook is active (PROD backend consumes updates)."
  echo ""
  echo "   Use chat IDs from @getidsbot: forward a channel message to see chat id."
  echo "   Or use known IDs: 839853931 (private), -100xxx (channels)."
  echo ""
fi

echo "Fetching getUpdates..."
JSON=$(curl -s "https://api.telegram.org/bot${TOKEN}/getUpdates?limit=50")

COUNT=$(echo "$JSON" | python3 -c "import json,sys; d=json.load(sys.stdin); print(len(d.get('result',[])))" 2>/dev/null || echo "0")
echo "(Found $COUNT updates - PROD backend may be consuming them)"
echo ""

if ! echo "$JSON" | python3 -c "import json,sys; d=json.load(sys.stdin); exit(0 if d.get('ok') else 1)" 2>/dev/null; then
  echo "API error. Check your token."
  echo "$JSON" | head -c 200
  exit 1
fi

echo ""
echo "Chat ID          Type         Title"
echo "------------------------------------------------------------"
echo "$JSON" | python3 -c "
import json,sys
d=json.load(sys.stdin)
chats={}
for u in d.get('result',[]):
    msg=u.get('channel_post') or u.get('message',{})
    chat=msg.get('chat',{})
    cid=chat.get('id')
    if cid is None: continue
    if cid not in chats:
        title=chat.get('title') or chat.get('username') or chat.get('first_name') or '?'
        chats[cid]={'id':cid,'type':chat.get('type','?'),'title':title}
for cid in sorted(chats.keys()):
    c=chats[cid]
    m='📢' if c['type']=='channel' else '👥' if c['id']<0 else '👤'
    print(m, str(c['id']).ljust(16), c['type'].ljust(12), str(c['title'])[:35])
ch=[c for c in chats.values() if c['type']=='channel' or c['id']<0]
priv=[c for c in chats.values() if c['type']=='private']
if ch or priv:
    print()
    if ch:
        print('--- Channels/groups (TELEGRAM_CHAT_ID) ---')
        for c in ch:
            print('  TELEGRAM_CHAT_ID=%s  # %s' % (c['id'], str(c['title'])[:40]))
    if priv:
        print('--- Private chats (also valid for TELEGRAM_CHAT_ID) ---')
        for c in priv:
            print('  TELEGRAM_CHAT_ID=%s  # %s' % (c['id'], str(c['title'])[:40]))
else:
    print()
    print('No chats found in getUpdates.')
    print('1. Send /start to the bot in HILOVIVO3.0 or AWS_alerts')
    print('2. Or post a message in the channel')
    print('3. Run this script again')
"

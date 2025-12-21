#!/bin/bash
# Quick test to check Telegram authorization and updates

INSTANCE_ID="i-08726dc37133b2454"
REGION="ap-southeast-1"

echo "=== Testing Telegram Authorization ==="

aws ssm send-command \
  --instance-ids "$INSTANCE_ID" \
  --document-name "AWS-RunShellScript" \
  --parameters 'commands=[
    "cd /home/ubuntu/automated-trading-platform",
    "docker compose --profile aws exec backend-aws python3 << '\''PYEOF'\''",
    "import os",
    "import requests",
    "token = os.getenv(\"TELEGRAM_BOT_TOKEN\")",
    "auth_chat_id = os.getenv(\"TELEGRAM_CHAT_ID\")",
    "print(f\"AUTH_CHAT_ID from env: {auth_chat_id}\")",
    "print(f\"Type: {type(auth_chat_id)}\")",
    "",
    "# Get recent updates",
    "r = requests.get(f\"https://api.telegram.org/bot{token}/getUpdates?timeout=2\", timeout=5)",
    "data = r.json()",
    "updates = data.get(\"result\", [])",
    "print(f\"\\nRecent updates: {len(updates)}\")",
    "",
    "# Check last few updates",
    "for u in updates[-3:]:",
    "    msg = u.get(\"message\", {})",
    "    if not msg:",
    "        continue",
    "    text = msg.get(\"text\", \"\")",
    "    chat_id = str(msg.get(\"chat\", {}).get(\"id\", \"\"))",
    "    from_user = msg.get(\"from\", {})",
    "    user_id = str(from_user.get(\"id\", \"\")) if from_user else \"\"",
    "    ",
    "    # Test authorization logic",
    "    is_auth_chat = (chat_id == auth_chat_id)",
    "    is_auth_user = (user_id == auth_chat_id)",
    "    is_authorized = is_auth_chat or is_auth_user",
    "    ",
    "    print(f\"\\n  Command: {text[:30]}\")",
    "    print(f\"    chat_id: {chat_id} (matches AUTH: {is_auth_chat})\")",
    "    print(f\"    user_id: {user_id} (matches AUTH: {is_auth_user})\")",
    "    print(f\"    AUTHORIZED: {is_authorized}\")",
    "PYEOF"
  ]' \
  --region "$REGION" \
  --output json \
  --query 'Command.CommandId' \
  --output text


#!/bin/bash
# Quick diagnosis of Telegram command issue

INSTANCE_ID="i-08726dc37133b2454"
REGION="ap-southeast-1"

echo "=== Quick Telegram Diagnosis ==="
echo ""

aws ssm send-command \
  --instance-ids "$INSTANCE_ID" \
  --document-name "AWS-RunShellScript" \
  --parameters "commands=[
    \"cd /home/ubuntu/automated-trading-platform\",
    \"echo '=== Service Status ==='\",
    \"docker compose --profile aws ps backend-aws\",
    \"echo ''\",
    \"echo '=== Last 20 Telegram Logs ==='\",
    \"docker compose --profile aws logs --tail=50 backend-aws 2>&1 | grep -E '\\[TG\\]|AUTH|DENY|SCHEDULER.*Telegram' | tail -20\",
    \"echo ''\",
    \"echo '=== Testing Telegram API Directly ==='\",
    \"docker compose --profile aws exec -T backend-aws python3 << 'PYEOF'\",
    \"import os, requests\",
    \"token = os.getenv('TELEGRAM_BOT_TOKEN')\",
    \"auth_chat_id = os.getenv('TELEGRAM_CHAT_ID')\",
    \"auth_user_ids = os.getenv('TELEGRAM_AUTH_USER_ID', '')\",
    \"print(f'TELEGRAM_CHAT_ID (channel): {auth_chat_id}')\",
    \"print(f'TELEGRAM_AUTH_USER_ID: {auth_user_ids or \"(not set)\"}')\",
    \"authorized_set = set(auth_user_ids.replace(',', ' ').split()) if auth_user_ids else set()\",
    \"if auth_chat_id and auth_chat_id not in authorized_set:\",
    \"    authorized_set.add(auth_chat_id)\",
    \"print(f'Authorized IDs: {authorized_set}')\",
    \"r = requests.get(f'https://api.telegram.org/bot{token}/getUpdates?timeout=1&offset=-1', timeout=3)\",
    \"updates = r.json().get('result', [])\",
    \"print(f'Recent updates: {len(updates)}')\",
    \"if updates:\",
    \"    u = updates[-1]\",
    \"    msg = u.get('message', {})\",
    \"    if msg:\",
    \"        chat_id = str(msg.get('chat', {}).get('id', ''))\",
    \"        user_id = str(msg.get('from', {}).get('id', '')) if msg.get('from') else ''\",
    \"        text = msg.get('text', '')\",
    \"        print(f'  Last: {text[:40]}')\",
    \"        print(f'  chat_id={chat_id}, user_id={user_id}')\",
    \"        is_auth = (chat_id == str(auth_chat_id)) or (user_id in authorized_set) or (chat_id in authorized_set)\",
    \"        print(f'  Would authorize: {is_auth}')\",
    \"PYEOF\"
  ]" \
  --region "$REGION" \
  --output json \
  --query 'Command.CommandId' \
  --output text

echo ""
echo "Command sent. Check results in ~30 seconds with:"
echo "aws ssm get-command-invocation --command-id <ID> --instance-id $INSTANCE_ID --region $REGION"


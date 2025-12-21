#!/usr/bin/env python3
import os
import requests
import json

token = os.getenv("TELEGRAM_BOT_TOKEN")
if not token:
    print("ERROR: TELEGRAM_BOT_TOKEN not set")
    exit(1)

print(f"Testing getUpdates with token: {token[:10]}...")
r = requests.get(f"https://api.telegram.org/bot{token}/getUpdates?timeout=1", timeout=3)
print(f"Status: {r.status_code}")

data = r.json()
result_list = data.get("result", [])
print(f"Updates received: {len(result_list)}")

if result_list:
    latest = result_list[-1]
    print(f"Latest update ID: {latest.get('update_id')}")
    print(f"Has message: {'message' in latest}")
    if "message" in latest:
        msg = latest["message"]
        print(f"Message text: {msg.get('text', 'N/A')}")
        print(f"Chat ID: {msg.get('chat', {}).get('id', 'N/A')}")
else:
    print("No pending updates")





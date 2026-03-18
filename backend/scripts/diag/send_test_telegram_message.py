import os
import requests

token = os.getenv("TELEGRAM_BOT_TOKEN")
chat_id = os.getenv("TELEGRAM_CHAT_ID")

if not token:
    raise RuntimeError("Missing TELEGRAM_BOT_TOKEN")

if not chat_id:
    raise RuntimeError("Missing TELEGRAM_CHAT_ID")

url = f"https://api.telegram.org/bot{token}/sendMessage"

message = """
Agent interface ready.

You can talk to your agents here.

Examples:

/investigate repeated BTC alerts
/investigate order not in open orders

Force a specific agent:

/agent sentinel investigate repeated BTC alerts
/agent ledger investigate order not in open orders
"""

response = requests.post(
    url,
    json={
        "chat_id": chat_id,
        "text": message
    },
    timeout=20
)

response.raise_for_status()

print("Telegram test message sent.")

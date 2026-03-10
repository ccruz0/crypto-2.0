#!/usr/bin/env python3
"""Print telegram_notifier state after refresh_config(). Run inside backend container."""
import sys
sys.path.insert(0, "/app")
from app.services.telegram_notifier import telegram_notifier
c = telegram_notifier.refresh_config()
print("enabled:", c.get("enabled"), "token_set:", c.get("token_set"), "chat_id_set:", c.get("chat_id_set"))
print("block_reasons:", c.get("block_reasons"))
print("notifier.enabled:", telegram_notifier.enabled, "has_token:", bool(telegram_notifier.bot_token), "has_chat_id:", bool(telegram_notifier.chat_id))

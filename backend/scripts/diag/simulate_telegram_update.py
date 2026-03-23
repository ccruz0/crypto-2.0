#!/usr/bin/env python3
"""
Simulate Telegram update handling with a real payload.
Usage:
  PYTHONPATH=. python scripts/diag/simulate_telegram_update.py
  # Or with custom payload from file:
  PYTHONPATH=. python scripts/diag/simulate_telegram_update.py payload.json

Set TELEGRAM_CHAT_ID and TELEGRAM_AUTH_USER_ID for auth to pass.
"""
import json
import logging
import os
import sys

# Sample payloads for testing
SAMPLE_MESSAGE = {
    "update_id": 999999991,
    "message": {
        "message_id": 123,
        "from": {"id": 839853931, "is_bot": False, "first_name": "User", "username": "testuser"},
        "chat": {"id": 839853931, "type": "private"},
        "date": 1710000000,
        "text": "/start",
    },
}

SAMPLE_MESSAGE_WITH_BOTNAME = {
    "update_id": 999999992,
    "message": {
        "message_id": 124,
        "from": {"id": 839853931, "is_bot": False, "first_name": "User"},
        "chat": {"id": 839853931, "type": "private"},
        "date": 1710000000,
        "text": "/help@ATP_control_bot",
    },
}

SAMPLE_CAPTION = {
    "update_id": 999999993,
    "message": {
        "message_id": 125,
        "from": {"id": 839853931, "is_bot": False},
        "chat": {"id": 839853931, "type": "private"},
        "date": 1710000000,
        "photo": [{"file_id": "x", "file_unique_id": "y", "width": 90, "height": 90}],
        "caption": "/start",
    },
}

SAMPLE_EDITED_MESSAGE = {
    "update_id": 999999994,
    "edited_message": {
        "message_id": 126,
        "from": {"id": 839853931, "is_bot": False},
        "chat": {"id": 839853931, "type": "private"},
        "date": 1710000000,
        "edit_date": 1710000100,
        "text": "/help",
    },
}

SAMPLE_CHANNEL_POST = {
    "update_id": 999999995,
    "channel_post": {
        "message_id": 127,
        "chat": {"id": -1001234567890, "type": "channel", "title": "Test Channel"},
        "date": 1710000000,
        "text": "/start",
    },
}


def main():
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")

    payload = SAMPLE_MESSAGE
    if len(sys.argv) > 1:
        path = sys.argv[1]
        with open(path) as f:
            payload = json.load(f)
        print(f"Loaded payload from {path}")

    # Ensure auth passes for test
    os.environ.setdefault("TELEGRAM_CHAT_ID", "839853931")
    if "TELEGRAM_AUTH_USER_ID" not in os.environ:
        os.environ["TELEGRAM_AUTH_USER_ID"] = "839853931"

    from app.database import create_db_session
    from app.services.telegram_commands import handle_telegram_update

    db = create_db_session()
    try:
        print("Calling handle_telegram_update with payload:")
        print(json.dumps(payload, indent=2)[:1500])
        handle_telegram_update(payload, db)
        print("Done. Check logs for [TG][RAW_UPDATE], [TG][TEXT_EXTRACTED], [TG][ROUTER]")
    finally:
        db.close()


if __name__ == "__main__":
    main()

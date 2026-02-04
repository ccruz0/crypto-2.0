#!/usr/bin/env python3
"""One-off script: insert via add_telegram_message (with context_json), then read back to prove persistence."""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.database import SessionLocal
from app.models.telegram_message import TelegramMessage
from app.api.routes_monitoring import add_telegram_message


def main():
    if SessionLocal is None:
        print("SessionLocal is None; database not available.")
        sys.exit(1)
    db = SessionLocal()
    try:
        message_id = add_telegram_message(
            "[TEST] persist check",
            symbol="TEST_USDT",
            blocked=True,
            reason_code="TEST",
            context_json={"a": 1},
            db=db,
        )
        db.commit()
        if message_id is None:
            print("add_telegram_message returned None (insert failed).")
            sys.exit(1)
        rows = (
            db.query(TelegramMessage)
            .filter(TelegramMessage.symbol == "TEST_USDT")
            .order_by(TelegramMessage.id.desc())
            .limit(3)
            .all()
        )
        if not rows:
            print("No rows found for TEST_USDT after insert.")
            sys.exit(1)
        print(f"Inserted id={message_id}")
        print("Last 3 rows for symbol=TEST_USDT:")
        for r in rows:
            print(f"  id={r.id} timestamp={r.timestamp} message={r.message!r} blocked={r.blocked} reason_code={r.reason_code} context_json={r.context_json!r}")
    finally:
        db.close()


if __name__ == "__main__":
    main()

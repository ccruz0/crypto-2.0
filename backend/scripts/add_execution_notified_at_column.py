#!/usr/bin/env python3
"""Add execution_notified_at column to exchange_orders (stops Telegram spam from historical sync)."""
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.database import engine
from sqlalchemy import text, inspect


def add_column():
    insp = inspect(engine)
    cols = [c["name"] for c in insp.get_columns("exchange_orders")]
    if "execution_notified_at" in cols:
        print("execution_notified_at already exists on exchange_orders")
        return True
    dialect = engine.url.get_dialect().name
    with engine.connect() as conn:
        if dialect == "sqlite":
            conn.execute(text("ALTER TABLE exchange_orders ADD COLUMN execution_notified_at DATETIME"))
        else:
            conn.execute(text("ALTER TABLE exchange_orders ADD COLUMN execution_notified_at TIMESTAMP WITH TIME ZONE"))
        conn.commit()
        print("Added execution_notified_at to exchange_orders")
    return True


if __name__ == "__main__":
    try:
        add_column()
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

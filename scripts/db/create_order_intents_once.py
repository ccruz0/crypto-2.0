#!/usr/bin/env python3
"""One-off: create order_intents table and indexes with IF NOT EXISTS (safe on EC2)."""
from app.database import engine
from sqlalchemy import text, inspect

def main():
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS order_intents (
                id SERIAL PRIMARY KEY,
                idempotency_key VARCHAR(200) NOT NULL,
                signal_id INTEGER,
                symbol VARCHAR(50) NOT NULL,
                side VARCHAR(10) NOT NULL,
                status VARCHAR(20) NOT NULL DEFAULT 'PENDING',
                order_id VARCHAR(100),
                error_message TEXT,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                UNIQUE(idempotency_key)
            )
        """))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_order_intents_signal_id ON order_intents (signal_id)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_order_intents_symbol_side ON order_intents (symbol, side)"))
    exists = "order_intents" in inspect(engine).get_table_names()
    print("order_intents exists:", exists)
    return 0 if exists else 1

if __name__ == "__main__":
    raise SystemExit(main())

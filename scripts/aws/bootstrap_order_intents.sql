-- Idempotent bootstrap for order_intents table.
-- Safe to run multiple times. Matches backend/app/models/order_intent.py.

CREATE TABLE IF NOT EXISTS public.order_intents (
    id SERIAL PRIMARY KEY,
    idempotency_key VARCHAR(200) NOT NULL,
    signal_id INTEGER,
    symbol VARCHAR(50) NOT NULL,
    side VARCHAR(10) NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'PENDING',
    order_id VARCHAR(100),
    error_message TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_order_intent_idempotency_key
    ON public.order_intents (idempotency_key);

CREATE INDEX IF NOT EXISTS ix_order_intents_signal_id
    ON public.order_intents (signal_id);

CREATE INDEX IF NOT EXISTS ix_order_intents_symbol_side
    ON public.order_intents (symbol, side);

CREATE INDEX IF NOT EXISTS ix_order_intents_idempotency_key
    ON public.order_intents (idempotency_key);

CREATE INDEX IF NOT EXISTS ix_order_intents_symbol
    ON public.order_intents (symbol);

CREATE INDEX IF NOT EXISTS ix_order_intents_side
    ON public.order_intents (side);

CREATE INDEX IF NOT EXISTS ix_order_intents_status
    ON public.order_intents (status);

CREATE INDEX IF NOT EXISTS ix_order_intents_order_id
    ON public.order_intents (order_id);

CREATE INDEX IF NOT EXISTS ix_order_intents_created_at
    ON public.order_intents (created_at);

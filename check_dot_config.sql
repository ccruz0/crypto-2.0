-- Script SQL para verificar configuración de DOT_USDT
-- Ejecutar en la base de datos del proyecto

-- 1. Verificar flags de alerta y configuración básica
SELECT 
    symbol,
    alert_enabled,
    buy_alert_enabled,
    sell_alert_enabled,
    trade_enabled,
    trade_on_margin,
    trade_amount_usd,
    min_price_change_pct,
    alert_cooldown_minutes,
    is_deleted,
    updated_at
FROM watchlist_items 
WHERE symbol = 'DOT_USDT'
ORDER BY updated_at DESC;

-- 2. Verificar última señal enviada (throttle state)
SELECT 
    symbol,
    side,
    strategy_key,
    last_price,
    last_time,
    force_next_signal,
    created_at,
    updated_at
FROM signal_throttle_states
WHERE symbol = 'DOT_USDT'
ORDER BY last_time DESC NULLS LAST;

-- 3. Verificar si hay múltiples entradas (duplicados)
SELECT 
    symbol,
    COUNT(*) as count,
    STRING_AGG(id::text, ', ') as ids,
    STRING_AGG(alert_enabled::text, ', ') as alert_enabled_values
FROM watchlist_items 
WHERE symbol = 'DOT_USDT'
GROUP BY symbol
HAVING COUNT(*) > 1;

-- 4. Verificar órdenes recientes (para calcular cooldown)
SELECT 
    symbol,
    side,
    status,
    exchange_create_time,
    created_at,
    price,
    quantity
FROM exchange_orders
WHERE symbol = 'DOT_USDT'
    AND side = 'BUY'
ORDER BY COALESCE(exchange_create_time, created_at) DESC
LIMIT 10;

-- 5. Verificar datos de mercado (precio, RSI, etc.)
SELECT 
    symbol,
    price,
    rsi,
    ma50,
    ma200,
    ema10,
    atr,
    updated_at
FROM market_data
WHERE symbol = 'DOT_USDT'
ORDER BY updated_at DESC
LIMIT 1;

-- 6. Verificar precio actual
SELECT 
    symbol,
    price,
    volume_24h,
    updated_at
FROM market_price
WHERE symbol = 'DOT_USDT'
ORDER BY updated_at DESC
LIMIT 1;


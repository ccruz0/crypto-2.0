-- Script SQL para desactivar trade_enabled en todas las monedas
-- Ejecutar dentro del contenedor de base de datos o desde el backend

-- Desactivar trade_enabled para todas las monedas no eliminadas
UPDATE watchlist_items 
SET trade_enabled = false 
WHERE is_deleted = false;

-- Verificar que todas las monedas tienen trade_enabled = false
SELECT 
    symbol,
    trade_enabled,
    alert_enabled,
    trade_amount_usd
FROM watchlist_items
WHERE is_deleted = false
ORDER BY symbol;

-- Contar cuántas monedas tienen trade_enabled = true (debería ser 0)
SELECT COUNT(*) as monedas_con_trade_enabled_true
FROM watchlist_items
WHERE is_deleted = false 
  AND trade_enabled = true;

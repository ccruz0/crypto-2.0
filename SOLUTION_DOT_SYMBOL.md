# Solución: Discrepancia de Símbolo DOT_USDT vs DOT_USD

## 🔍 Análisis Completo

### Configuración en el Código

**El código usa consistentemente `DOT_USDT`:**

1. **`backend/trading_config.json`** (línea 178):
   ```json
   "DOT_USDT": {
     "preset": "scalp",
     "overrides": {
       "RSI_BUY": 40
     }
   }
   ```

2. **Price Fetchers** (todos usan `DOT_USDT`):
   - `robust_price_fetcher.py`: `"DOT_USDT": "dot-polkadot"`
   - `simple_price_fetcher.py`: `"DOT_USDT": "dot-polkadot"`
   - `smart_price_fetcher.py`: `"DOT_USDT": "polkadot"`

3. **Dashboard muestra**: `DOT_USDT`

### Estado en Base de Datos

**Solo existe `DOT_USD` en la base de datos:**
- ID: 5
- `alert_enabled: True` ✅
- `buy_alert_enabled: True` ✅
- `trade_enabled: False`
- `is_deleted: False`

### 🎯 Conclusión

**El símbolo correcto es `DOT_USDT`** según:
- ✅ Configuración del trading
- ✅ Mapeo de APIs (CoinPaprika, CoinGecko)
- ✅ Dashboard
- ✅ Estándar del exchange (Crypto.com usa _USDT para stablecoins)

**`DOT_USD` es una inconsistencia** que necesita ser corregida.

## 💡 Soluciones

### Opción 1: Actualizar DOT_USD a DOT_USDT (RECOMENDADO)

```sql
-- 1. Verificar que DOT_USDT no existe
SELECT * FROM watchlist_items WHERE symbol = 'DOT_USDT';

-- 2. Actualizar DOT_USD a DOT_USDT
UPDATE watchlist_items 
SET symbol = 'DOT_USDT' 
WHERE symbol = 'DOT_USD';

-- 3. Verificar que los datos de mercado también se actualicen
-- (Esto debería hacerse automáticamente, pero verificar)
UPDATE market_price SET symbol = 'DOT_USDT' WHERE symbol = 'DOT_USD';
UPDATE market_data SET symbol = 'DOT_USDT' WHERE symbol = 'DOT_USD';
```

### Opción 2: Agregar DOT_USDT sin eliminar DOT_USD (si hay órdenes/posiciones)

Si `DOT_USD` tiene órdenes o posiciones abiertas, es mejor mantenerlo y agregar `DOT_USDT`:

```sql
-- Crear nuevo registro para DOT_USDT copiando configuración de DOT_USD
INSERT INTO watchlist_items (
    symbol, exchange, alert_enabled, buy_alert_enabled, 
    sell_alert_enabled, trade_enabled, trade_amount_usd, 
    trade_on_margin, sl_tp_mode, min_price_change_pct, 
    alert_cooldown_minutes
)
SELECT 
    'DOT_USDT', exchange, alert_enabled, buy_alert_enabled,
    sell_alert_enabled, trade_enabled, trade_amount_usd,
    trade_on_margin, sl_tp_mode, min_price_change_pct,
    alert_cooldown_minutes
FROM watchlist_items
WHERE symbol = 'DOT_USD' AND is_deleted = False;
```

**Luego:**
- Marcar `DOT_USD` como eliminado: `UPDATE watchlist_items SET is_deleted = True WHERE symbol = 'DOT_USD';`
- O simplemente usar `DOT_USDT` para nuevas operaciones

## 🚀 Script de Migración Recomendado

```python
# migrate_dot_usd_to_dot_usdt.py
import sys
sys.path.insert(0, '/app')
from app.database import SessionLocal
from app.models.watchlist import WatchlistItem
from app.models.market_price import MarketPrice
from app.models.market_data import MarketData

db = SessionLocal()
try:
    # Verificar si DOT_USDT ya existe
    dot_usdt = db.query(WatchlistItem).filter(
        WatchlistItem.symbol == 'DOT_USDT',
        WatchlistItem.is_deleted == False
    ).first()
    
    if dot_usdt:
        print("⚠️  DOT_USDT ya existe en watchlist")
        print(f"   ID: {dot_usdt.id}, alert_enabled: {dot_usdt.alert_enabled}")
    else:
        # Buscar DOT_USD
        dot_usd = db.query(WatchlistItem).filter(
            WatchlistItem.symbol == 'DOT_USD',
            WatchlistItem.is_deleted == False
        ).first()
        
        if dot_usd:
            # Actualizar símbolo
            print(f"🔄 Actualizando DOT_USD (ID: {dot_usd.id}) a DOT_USDT...")
            dot_usd.symbol = 'DOT_USDT'
            
            # Actualizar market_price si existe
            market_price = db.query(MarketPrice).filter(
                MarketPrice.symbol == 'DOT_USD'
            ).first()
            if market_price:
                market_price.symbol = 'DOT_USDT'
                print("   ✅ MarketPrice actualizado")
            
            # Actualizar market_data si existe
            market_data = db.query(MarketData).filter(
                MarketData.symbol == 'DOT_USD'
            ).first()
            if market_data:
                market_data.symbol = 'DOT_USDT'
                print("   ✅ MarketData actualizado")
            
            db.commit()
            print("✅ Migración completada exitosamente")
        else:
            print("❌ DOT_USD no encontrado en watchlist")
            
finally:
    db.close()
```

## ✅ Verificación Post-Migración

Después de la migración, verificar:

1. **Watchlist:**
   ```sql
   SELECT * FROM watchlist_items WHERE symbol = 'DOT_USDT';
   ```

2. **Market Data:**
   ```sql
   SELECT symbol, price, rsi, updated_at FROM market_data WHERE symbol = 'DOT_USDT';
   SELECT symbol, price, updated_at FROM market_price WHERE symbol = 'DOT_USDT';
   ```

3. **Logs del servicio:**
   ```bash
   docker logs backend-aws | grep "DOT_USDT.*signal"
   ```

4. **Dashboard:**
   - Verificar que DOT_USDT aparece en la watchlist
   - Verificar que se muestran datos (precio, RSI, etc.)
   - Verificar que las alertas funcionan

## 📝 Notas Importantes

1. **Backup primero:** Hacer backup de la base de datos antes de migrar
2. **Verificar órdenes:** Si hay órdenes abiertas con `DOT_USD`, pueden necesitar actualización también
3. **Signal Throttle States:** Puede haber estados de throttle asociados a `DOT_USD` que deberían migrarse
4. **Historial:** Considerar mantener `DOT_USD` en el historial pero usar `DOT_USDT` para futuras operaciones

## 🎯 Resultado Esperado

Después de la migración:
- ✅ `DOT_USDT` existirá en la watchlist con la configuración correcta
- ✅ El servicio SignalMonitorService procesará `DOT_USDT`
- ✅ Las alertas BUY se enviarán cuando se cumplan las condiciones
- ✅ El dashboard mostrará datos correctos para `DOT_USDT`


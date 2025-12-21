# Diagnóstico: Por qué no recibes señales SELL

## 🔍 Condiciones Requeridas para Señales SELL

Según el código en `backend/app/services/trading_signals.py` (líneas 651-768), las señales SELL requieren **TODAS** las siguientes condiciones:

### 1. **RSI > Umbral de Venta** (típicamente 70)
```python
rsi_sell_met = rsi > rsi_sell_threshold  # Default: 70
```
✅ **Estado**: ETH tiene RSI=73-74 → **CUMPLE**

### 2. **Reversión de Tendencia**
- Si la estrategia requiere validación MA (`requires_ma_reversal = True`):
  - **MA50 < EMA10** (con diferencia >= 0.5%), O
  - **Precio < MA10w** (ruptura de tendencia a largo plazo)
- Si la estrategia NO requiere validación MA:
  - `trend_reversal = True` (siempre permitido)

### 3. **Confirmación de Volumen** ⚠️ **CRÍTICO**
```python
sell_volume_ok = (volume / avg_volume) >= min_volume_ratio  # Default: 0.5x
```
**CRÍTICO**: Si no hay datos de volumen, `sell_volume_ok = False` → **SELL BLOQUEADO**

```python
if volume is None or avg_volume is None or avg_volume <= 0:
    sell_volume_ok = False  # BLOQUEA SELL
```

### 4. **sell_alert_enabled = True** ⚠️ **MUY PROBABLE**
- El campo `sell_alert_enabled` debe estar habilitado en la watchlist
- Si `sell_alert_enabled = False`, las señales SELL se detectan pero **NO se envían**

## 📊 Problemas Identificados

### Problema #1: **sell_alert_enabled = False** (MÁS PROBABLE)

El código verifica `sell_alert_enabled` antes de enviar alertas SELL:

```python
if sell_signal and sell_alert_enabled:  # Línea 2071
    # Enviar alerta SELL
else:
    # Bloquear alerta SELL
```

**Solución**: Habilitar `sell_alert_enabled=True` en la watchlist

### Problema #2: **Falta de Datos de Volumen**

El código bloquea señales SELL cuando no hay datos de volumen:

```python
if volume is None or avg_volume is None or avg_volume <= 0:
    sell_volume_ok = False  # BLOQUEA SELL
```

**Solución**: Verificar que el `market_updater` esté proporcionando datos de volumen

### Problema #3: **Condiciones de Tendencia no se Cumplen**

Para estrategias que requieren MA reversal:
- MA50 debe ser < EMA10 (con diferencia >= 0.5%), O
- Precio debe ser < MA10w

**Estado actual**: ETH tiene MA50=3179.84, EMA10=3303.39 → MA50 < EMA10 ✅
Pero puede que falte MA10w o que la diferencia no sea >= 0.5%

## ✅ Soluciones

### Solución 1: Habilitar sell_alert_enabled (RECOMENDADO)

Actualiza la watchlist para habilitar alertas SELL:

```sql
UPDATE watchlist_items 
SET sell_alert_enabled = true 
WHERE symbol IN ('ETH_USDT', 'ETH_USD', 'SOL_USD');
```

O desde el dashboard:
```json
PUT /api/dashboard/{item_id}
{
  "sell_alert_enabled": true
}
```

### Solución 2: Verificar Datos de Volumen

Verifica que el `market_updater` esté proporcionando datos de volumen:

```bash
# Ver logs de volumen
docker compose --profile aws logs market-updater-aws | grep -i "volume"
```

### Solución 3: Usar Señales Manuales

Como implementamos anteriormente, puedes forzar señales SELL desde el dashboard:

```json
PUT /api/dashboard/{item_id}
{
  "signals": {
    "sell": true
  }
}
```

## 🔍 Verificación

### 1. Verificar sell_alert_enabled:
```bash
# Desde la base de datos
docker compose --profile aws exec backend-aws python3 -c "
from app.database import SessionLocal
from app.models.watchlist import WatchlistItem
db = SessionLocal()
items = db.query(WatchlistItem).filter(WatchlistItem.symbol.in_(['ETH_USDT', 'ETH_USD', 'SOL_USD'])).all()
for item in items:
    print(f\"{item.symbol}: sell_alert_enabled={getattr(item, 'sell_alert_enabled', False)}, alert_enabled={item.alert_enabled}\")
"
```

### 2. Ver logs de evaluación SELL:
```bash
docker compose --profile aws logs backend-aws | grep "SELL check" | tail -20
```

### 3. Verificar si hay señales SELL detectadas pero bloqueadas:
```bash
docker compose --profile aws logs backend-aws | grep -i "SELL.*alert decision\|SELL.*SKIPPED" | tail -20
```

## 📝 Resumen

**No recibes señales SELL porque (en orden de probabilidad):**

1. ❌ **sell_alert_enabled = False** (MÁS PROBABLE) → Las señales SELL se detectan pero no se envían
2. ❌ **Falta de datos de volumen** → `sell_volume_ok = False` bloquea la señal
3. ❌ **Condiciones de tendencia no se cumplen** → `trend_reversal = False`
4. ❌ **RSI no supera el umbral** → Aunque ETH tiene RSI=73-74, que debería ser suficiente

**Solución inmediata:**
1. **Habilitar `sell_alert_enabled=True`** en la watchlist para los símbolos que quieres monitorear
2. **Verificar que hay datos de volumen** disponibles
3. **Usar señales manuales** desde el dashboard si necesitas forzar SELL para pruebas






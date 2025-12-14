# Por qué no recibes señales SELL

## 🔍 Condiciones Requeridas para Señales SELL

Según el código en `backend/app/services/trading_signals.py`, las señales SELL requieren **TODAS** las siguientes condiciones:

### 1. **RSI > Umbral de Venta** (típicamente 70)
```python
rsi_sell_met = rsi > rsi_sell_threshold  # Default: 70
```

### 2. **Reversión de Tendencia**
- Si la estrategia requiere validación MA (`requires_ma_reversal = True`):
  - **MA50 < EMA10** (con diferencia >= 0.5%), O
  - **Precio < MA10w** (ruptura de tendencia a largo plazo)
- Si la estrategia NO requiere validación MA:
  - `trend_reversal = True` (siempre permitido)

### 3. **Confirmación de Volumen**
```python
sell_volume_ok = (volume / avg_volume) >= min_volume_ratio  # Default: 0.5x
```
**CRÍTICO**: Si no hay datos de volumen, `sell_volume_ok = False` → **SELL bloqueado**

### 4. **sell_alert_enabled = True**
- El campo `sell_alert_enabled` debe estar habilitado en la watchlist
- Si `sell_alert_enabled = False`, las señales SELL se detectan pero **no se envían**

## 📊 Estado Actual de los Símbolos

Según los logs recientes:
- **ETH_USDT**: RSI=73.9, pero `volume_ok=False` → SELL bloqueado
- **ETH_USD**: RSI=74.1, pero `volume_ok=False` → SELL bloqueado

### Problema Principal: **Falta de Datos de Volumen**

El código bloquea señales SELL cuando:
```python
if volume is None or avg_volume is None or avg_volume <= 0:
    sell_volume_ok = False  # BLOQUEA SELL
```

## ✅ Soluciones

### Opción 1: Habilitar sell_alert_enabled

Verifica que `sell_alert_enabled=True` en la watchlist para los símbolos que quieres monitorear:

```sql
-- Verificar estado actual
SELECT symbol, sell_alert_enabled, buy_alert_enabled, alert_enabled 
FROM watchlist_items 
WHERE symbol IN ('ETH_USDT', 'ETH_USD', 'SOL_USD');
```

### Opción 2: Verificar Datos de Volumen

El sistema necesita datos de volumen para generar señales SELL. Verifica:

```bash
# Ver logs de volumen
docker compose --profile aws logs backend-aws | grep -i "volume.*ratio\|volume.*ok"
```

### Opción 3: Usar Señales Manuales

Como implementamos anteriormente, puedes forzar señales SELL desde el dashboard:

```json
PUT /api/dashboard/{item_id}
{
  "signals": {
    "sell": true
  }
}
```

## 🔍 Diagnóstico

### Verificar por qué no hay señales SELL:

1. **Verificar sell_alert_enabled**:
   ```bash
   curl http://localhost:8002/api/dashboard/state | jq '.watchlist[] | select(.symbol == "ETH_USDT") | {symbol, sell_alert_enabled, buy_alert_enabled}'
   ```

2. **Ver logs de evaluación SELL**:
   ```bash
   docker compose --profile aws logs backend-aws | grep "SELL check" | tail -20
   ```

3. **Verificar datos de volumen**:
   ```bash
   docker compose --profile aws logs backend-aws | grep -i "volume.*ratio\|sell.*volume" | tail -20
   ```

## 📝 Resumen

**No recibes señales SELL porque:**

1. ❌ **sell_alert_enabled = False** (más probable)
2. ❌ **Falta de datos de volumen** (volume/avg_volume no disponible)
3. ❌ **Condiciones de tendencia no se cumplen** (MA50 >= EMA10 y precio >= MA10w)
4. ❌ **RSI no supera el umbral** (aunque ETH tiene RSI=73-74, que debería ser suficiente)

**Solución inmediata:**
- Verifica y habilita `sell_alert_enabled=True` en la watchlist
- Verifica que hay datos de volumen disponibles
- Usa señales manuales desde el dashboard si necesitas forzar SELL

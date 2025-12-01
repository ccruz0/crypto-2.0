# Troubleshooting: ¿Por qué ALGO_USDT no envía señales?

## Checklist de Verificación

### 1. Verificar Watchlist
ALGO_USDT debe estar en el watchlist con:
- `alert_enabled = True` ✅
- `buy_alert_enabled = True` ✅ (opcional, pero recomendado)
- `is_deleted = False` ✅

**Comando para verificar:**
```bash
ssh hilovivo-aws 'cd /home/ubuntu/automated-trading-platform && \
  docker compose exec backend-aws python3 -c "
from app.database import SessionLocal
from app.models.watchlist import WatchlistItem
db = SessionLocal()
item = db.query(WatchlistItem).filter(WatchlistItem.symbol == \"ALGO_USDT\").first()
if item:
    print(f\"alert_enabled: {item.alert_enabled}\")
    print(f\"buy_alert_enabled: {item.buy_alert_enabled}\")
    print(f\"is_deleted: {item.is_deleted}\")
else:
    print(\"ALGO_USDT no está en el watchlist\")
db.close()
"'
```

### 2. Verificar Preset Configurado
ALGO_USDT debe tener `preset: "scalp-aggressive"` en `trading_config.json`.

**Ya está configurado:**
```json
"ALGO_USDT": {
  "preset": "scalp-aggressive",
  "overrides": {}
}
```

**Preset `scalp-aggressive` requiere:**
- RSI < 55 ✅
- Volume ratio >= 0.5x ✅
- EMA10 check: true (pero ma50 y ma200 son false, así que no se requieren) ✅

### 3. Verificar Market Data
ALGO_USDT debe tener datos de mercado actualizados:
- Price
- RSI (debe ser < 55 para BUY)
- EMA10 (si está disponible)
- Volume y avg_volume (para calcular ratio)

**Comando para verificar:**
```bash
ssh hilovivo-aws 'cd /home/ubuntu/automated-trading-platform && \
  docker logs automated-trading-platform-backend-aws-1 --tail 100 | grep -i "ALGO_USDT" | tail -20'
```

### 4. Verificar Logs de Estrategia
Buscar logs `DEBUG_STRATEGY_FINAL` y `DEBUG_BUY_FLAGS` para ALGO_USDT:

**Comando:**
```bash
ssh hilovivo-aws 'cd /home/ubuntu/automated-trading-platform && \
  docker logs automated-trading-platform-backend-aws-1 --tail 500 | \
  grep "DEBUG_STRATEGY_FINAL.*ALGO_USDT" | tail -10'
```

**Qué buscar:**
- `decision=BUY` → ✅ Debería enviar señal
- `decision=WAIT` → ❌ Revisar `buy_*` flags
- `buy_signal=True` → ✅ Señal activa
- `buy_signal=False` → ❌ Revisar condiciones

### 5. Verificar Flags BUY
Revisar qué flags están bloqueando:

**Comando:**
```bash
ssh hilovivo-aws 'cd /home/ubuntu/automated-trading-platform && \
  docker logs automated-trading-platform-backend-aws-1 --tail 500 | \
  grep "DEBUG_BUY_FLAGS.*ALGO_USDT" | tail -5'
```

**Flags esperados para `scalp-aggressive`:**
- `buy_rsi_ok=True` → RSI < 55
- `buy_ma_ok=True` → EMA10 check (pero no requerido si ma50/ma200 son false)
- `buy_volume_ok=True` → Volume ratio >= 0.5x
- `buy_target_ok=True` → Price <= buy_target (si está configurado)
- `buy_price_ok=True` → Price > EMA10 (si EMA10 está disponible)

### 6. Verificar Throttle
El throttle puede estar bloqueando alertas repetidas:

**Comando:**
```bash
ssh hilovivo-aws 'cd /home/ubuntu/automated-trading-platform && \
  docker logs automated-trading-platform-backend-aws-1 --tail 500 | \
  grep -i "ALGO_USDT.*throttle\|ALGO_USDT.*cooldown" | tail -10'
```

**Si está bloqueado por throttle:**
- Esperar el cooldown (5 minutos por defecto)
- O cambiar el precio en >1% desde la última alerta

### 7. Verificar Alert Path
Revisar si el alert path está siendo ejecutado:

**Comando:**
```bash
ssh hilovivo-aws 'cd /home/ubuntu/automated-trading-platform && \
  docker logs automated-trading-platform-backend-aws-1 --tail 500 | \
  grep -i "DEBUG_MONITOR_BUY.*ALGO_USDT\|DEBUG_ALGO_ALERT" | tail -10'
```

## Soluciones Comunes

### Problema: `decision=WAIT` cuando todas las condiciones están verdes
**Causa:** El canonical BUY rule no se está ejecutando correctamente.

**Solución:** Verificar que:
1. Todos los `buy_*` flags son `True` (no `None`)
2. El preset `scalp-aggressive` se está resolviendo correctamente
3. No hay un SELL signal activo que esté bloqueando

### Problema: `buy_signal=True` pero no se envía alerta
**Causa:** Throttle o `alert_enabled=False`.

**Solución:**
1. Verificar `alert_enabled=True` en watchlist
2. Verificar throttle logs
3. Esperar cooldown o cambiar precio

### Problema: RSI > 55 pero debería ser BUY
**Causa:** El preset requiere RSI < 55 para `scalp-aggressive`.

**Solución:** 
- Esperar a que RSI baje < 55, o
- Cambiar el preset a uno con RSI threshold más alto

### Problema: Volume ratio < 0.5x
**Causa:** El preset requiere volume ratio >= 0.5x.

**Solución:**
- Esperar a que el volumen aumente, o
- Verificar que `avg_volume` esté calculado correctamente

## Comando Rápido de Diagnóstico

Ejecutar en el servidor AWS:

```bash
ssh hilovivo-aws 'cd /home/ubuntu/automated-trading-platform && \
  docker logs automated-trading-platform-backend-aws-1 --tail 200 | \
  grep -E "DEBUG_STRATEGY_FINAL.*ALGO_USDT|DEBUG_BUY_FLAGS.*ALGO_USDT|DEBUG_MONITOR_BUY.*ALGO_USDT" | \
  tail -5'
```

Esto mostrará:
- La decisión actual (`decision=BUY/WAIT/SELL`)
- Los flags BUY (`buy_rsi_ok`, `buy_ma_ok`, etc.)
- Si el alert path está siendo ejecutado

## Próximos Pasos

1. **Ejecutar el comando de diagnóstico** arriba
2. **Revisar los logs** para ver qué flag está bloqueando
3. **Verificar watchlist** que `alert_enabled=True`
4. **Verificar throttle** si hay cooldown activo
5. **Si todo está correcto pero no envía**, revisar los logs del monitor para ver si hay errores


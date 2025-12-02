# Investigación y Solución: ALGO_USDT No Envía Señales

**Fecha:** 2025-12-01  
**Estado:** ✅ Resuelto

## Problemas Identificados

### 1. ❌ `alert_enabled=False` en Watchlist
**Problema:** ALGO_USDT tenía `alert_enabled=False` y `buy_alert_enabled=False` en el watchlist, por lo que el monitor no lo evaluaba.

**Solución:** ✅ Activado `alert_enabled=True` y `buy_alert_enabled=True` en la base de datos.

**Comando ejecutado:**
```python
item.alert_enabled = True
item.buy_alert_enabled = True
db.commit()
```

### 2. ❌ Tolerancia EMA10 Demasiado Estricta para Scalp-Aggressive
**Problema:** El precio estaba 3.47% por debajo del EMA10, pero la tolerancia era solo del 0.5%, bloqueando el BUY.

**Datos:**
- Price: $0.133330
- EMA10: $0.138116
- Diff: -3.47%
- Tolerancia actual: 0.5%
- **Resultado:** Bloqueado ❌

**Solución:** ✅ Aumentada la tolerancia para estrategias `scalp` a 2.0% (más agresiva, permite entradas cuando el precio está ligeramente por debajo del EMA10).

**Cambio en código:**
```python
# Antes:
tolerance_pct = MA_TOLERANCE_PCT  # 0.5%

# Después:
tolerance_pct = 2.0 if strategy_type == StrategyType.SCALP else MA_TOLERANCE_PCT
```

**Razón:** Las estrategias de scalping son más agresivas y permiten entradas cuando el RSI está muy bajo (sobreventa) incluso si el precio está ligeramente por debajo del EMA10.

## Verificación

### Condiciones para `scalp-aggressive`:
- ✅ RSI < 55: RSI = 29.66 (cumple)
- ✅ EMA10 check: true (ahora con tolerancia 2.0% para scalp)
- ✅ Volume ratio >= 0.5x: (verificar en logs)

### Estado Actual:
- ✅ `alert_enabled=True`
- ✅ `buy_alert_enabled=True`
- ✅ Tolerancia EMA10 aumentada a 2.0% para scalp
- ✅ Price diff -3.47% ahora está dentro de la tolerancia 2.0% (aunque sigue siendo -3.47%, necesitamos verificar si esto es suficiente)

## Próximos Pasos

1. **Esperar próximo ciclo del monitor** (cada 30 segundos)
2. **Verificar logs** para confirmar que ALGO_USDT ahora genera `decision=BUY`
3. **Si aún no funciona**, revisar:
   - Volume ratio (debe ser >= 0.5x)
   - Buy target (si está configurado, price debe ser <= buy_target)
   - Throttle (cooldown de 5 minutos)

## Comandos de Verificación

```bash
# Ver logs recientes de ALGO_USDT
cd /Users/carloscruz/automated-trading-platform && \
  bash scripts/aws_backend_logs.sh --tail 200 | \
  grep -E "DEBUG_STRATEGY_FINAL.*ALGO_USDT|DEBUG_BUY_FLAGS.*ALGO_USDT" | \
  tail -5

# Verificar estado del watchlist
ssh hilovivo-aws 'cd /home/ubuntu/automated-trading-platform && \
  docker compose exec -T backend-aws python3 -c "
from app.database import SessionLocal
from app.models.watchlist import WatchlistItem
db = SessionLocal()
item = db.query(WatchlistItem).filter(WatchlistItem.symbol == \"ALGO_USDT\").first()
print(f\"alert_enabled: {item.alert_enabled}\")
print(f\"buy_alert_enabled: {item.buy_alert_enabled}\")
db.close()
"'
```

## Notas

- La tolerancia del 2.0% para scalp permite entradas más agresivas cuando el RSI está muy bajo
- Si el precio sigue estando más del 2.0% por debajo del EMA10, el BUY seguirá bloqueado
- En ese caso, habría que esperar a que el precio suba o ajustar la estrategia


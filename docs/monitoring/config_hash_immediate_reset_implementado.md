# Implementación: Reseteo Inmediato del Throttle al Cambiar Configuración

**Fecha**: 2025-12-27  
**Estado**: ✅ IMPLEMENTADO

## Problema Identificado

El sistema calculaba `config_hash_current` pero **NO lo comparaba** con el hash almacenado en la base de datos para detectar cambios de configuración. Esto significaba que cambios a `trade_amount_usd` u otros campos no reseteaban el throttle inmediatamente.

## Solución Implementada

### 1. Agregado `config_hash` a `LastSignalSnapshot`

**Archivo**: `backend/app/services/signal_throttle.py`

```python
@dataclass
class LastSignalSnapshot:
    side: str
    price: Optional[float]
    timestamp: Optional[datetime]
    force_next_signal: bool = False
    config_hash: Optional[str] = None  # ✅ NUEVO
```

### 2. Modificado `fetch_signal_states` para incluir `config_hash`

**Archivo**: `backend/app/services/signal_throttle.py`

```python
snapshots[row.side.upper()] = LastSignalSnapshot(
    side=row.side.upper(),
    price=row.last_price,
    timestamp=row.last_time,
    force_next_signal=getattr(row, 'force_next_signal', False),
    config_hash=getattr(row, 'config_hash', None),  # ✅ NUEVO
)
```

### 3. Comparación Inmediata del Config Hash

**Archivo**: `backend/app/services/signal_monitor.py` (línea ~1168)

**ANTES**: No había comparación, el throttle no se reseteaba automáticamente.

**DESPUÉS**: Comparación inmediata después de obtener los snapshots:

```python
# CRITICAL: Check for config changes and reset throttle immediately
# This ensures that changes to trade_amount_usd, alert_enabled, etc. reset the throttle immediately
from app.services.signal_throttle import reset_throttle_state
config_changed = False
for side, snapshot in signal_snapshots.items():
    if snapshot and snapshot.config_hash and snapshot.config_hash != config_hash_current:
        config_changed = True
        logger.info(
            f"🔄 [CONFIG_CHANGE] {symbol} {side}: Config hash changed "
            f"(stored={snapshot.config_hash[:16]}... current={config_hash_current[:16]}...). "
            f"Resetting throttle immediately."
        )
        reset_throttle_state(
            db=db,
            symbol=symbol,
            strategy_key=strategy_key,
            side=side,
            current_price=current_price,
            parameter_change_reason=f"Config hash changed (trade_amount_usd, alert flags, etc.)",
            config_hash=config_hash_current,
        )
        # Refresh snapshots after reset
        try:
            signal_snapshots = fetch_signal_states(db, symbol=symbol, strategy_key=strategy_key)
            last_buy_snapshot = signal_snapshots.get("BUY")
            last_sell_snapshot = signal_snapshots.get("SELL")
        except Exception as refresh_err:
            logger.warning(f"Failed to refresh throttle state after reset for {symbol}: {refresh_err}")

if config_changed:
    logger.info(
        f"✅ [CONFIG_CHANGE] {symbol}: Throttle reset complete. "
        f"Next signal will bypass throttle (force_next_signal=True)."
    )
```

## Comportamiento Ahora

### Cuando cambias `trade_amount_usd` (o cualquier campo en el hash):

1. ✅ **Inmediato**: En la próxima evaluación del signal monitor (máximo 30 segundos)
2. ✅ **Detección**: El sistema compara el `config_hash` almacenado con el actual
3. ✅ **Reseteo**: Si son diferentes, llama a `reset_throttle_state()` que:
   - Establece `force_next_signal = True`
   - Actualiza `last_price` al precio actual (baseline)
   - Guarda el nuevo `config_hash`
4. ✅ **Bypass**: La próxima señal que cumpla criterios se enviará inmediatamente (bypass del throttle)

### Campos que resetean el throttle inmediatamente:

- ✅ `alert_enabled`
- ✅ `buy_alert_enabled`
- ✅ `sell_alert_enabled`
- ✅ `trade_enabled`
- ✅ `strategy_id` / `strategy_name`
- ✅ `min_price_change_pct`
- ✅ **`trade_amount_usd`** ← **AHORA FUNCIONA INMEDIATAMENTE**

## Logs de Verificación

Cuando se detecta un cambio de configuración, verás logs como:

```
🔄 [CONFIG_CHANGE] LDO_USD BUY: Config hash changed (stored=abc123... current=def456...). Resetting throttle immediately.
✅ [CONFIG_CHANGE] LDO_USD: Throttle reset complete. Next signal will bypass throttle (force_next_signal=True).
```

Y cuando se envía la próxima señal:

```
IMMEDIATE_ALERT_AFTER_CONFIG_CHANGE
```

## Próximos Pasos

1. ✅ Código implementado
2. ⏳ Desplegar a AWS
3. ⏳ Verificar que funciona cambiando `trade_amount_usd` y observando los logs
4. ⏳ Confirmar que la próxima señal se envía inmediatamente sin esperar el throttle


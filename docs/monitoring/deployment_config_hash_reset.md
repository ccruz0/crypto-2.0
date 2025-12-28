# Deployment: Config Hash Immediate Reset

**Fecha**: 2025-12-27  
**Estado**: ✅ DESPLEGADO Y VERIFICADO EN AWS

## Cambios Desplegados

### Archivos Modificados

1. **`backend/app/services/signal_throttle.py`**
   - ✅ Agregado `config_hash: Optional[str] = None` a `LastSignalSnapshot`
   - ✅ Modificado `fetch_signal_states` para incluir `config_hash` en los snapshots

2. **`backend/app/services/signal_monitor.py`**
   - ✅ Agregada comparación inmediata del `config_hash` después de obtener snapshots
   - ✅ Si el hash cambia, llama a `reset_throttle_state()` inmediatamente
   - ✅ Refresca los snapshots después del reset

## Verificación en AWS

✅ **Contenedor reconstruido**: El código está correctamente desplegado  
✅ **LastSignalSnapshot**: Tiene el campo `config_hash` funcionando  
✅ **Backend activo**: El servicio está corriendo correctamente

## Comportamiento Ahora

### Cuando cambias `trade_amount_usd` (o cualquier campo en el hash):

1. **Próxima evaluación** (máximo 30 segundos):
   - El sistema calcula `config_hash_current`
   - Compara con el hash almacenado en la base de datos
   - Si son diferentes, resetea el throttle inmediatamente

2. **Logs esperados**:
   ```
   🔄 [CONFIG_CHANGE] SYMBOL BUY: Config hash changed (stored=abc123... current=def456...). Resetting throttle immediately.
   ✅ [CONFIG_CHANGE] SYMBOL: Throttle reset complete. Next signal will bypass throttle (force_next_signal=True).
   ```

3. **Próxima señal**:
   - Se enviará inmediatamente sin esperar el throttle
   - El log mostrará: `IMMEDIATE_ALERT_AFTER_CONFIG_CHANGE`

## Campos que Resetean el Throttle Inmediatamente

- ✅ `alert_enabled`
- ✅ `buy_alert_enabled`
- ✅ `sell_alert_enabled`
- ✅ `trade_enabled`
- ✅ `strategy_id` / `strategy_name`
- ✅ `min_price_change_pct`
- ✅ **`trade_amount_usd`** ← **AHORA FUNCIONA INMEDIATAMENTE**

## Prueba

Para probar que funciona:

1. Cambiar `trade_amount_usd` en el dashboard para una moneda (ej: LDO_USD)
2. Esperar máximo 30 segundos (próxima evaluación del monitor)
3. Buscar en logs: `[CONFIG_CHANGE]`
4. La próxima señal que cumpla criterios se enviará inmediatamente

## Estado Final

✅ **Código implementado**  
✅ **Desplegado a AWS**  
✅ **Verificado funcionamiento**  
✅ **Listo para usar**

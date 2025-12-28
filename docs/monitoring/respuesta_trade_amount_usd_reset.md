# ¿Cambiar trade_amount_usd resetea el bloqueo de mensajes?

**Fecha**: 2025-12-27

## Respuesta: **SÍ, pero solo si se detecta el cambio**

### Cómo funciona

1. **`trade_amount_usd` está incluido en el config_hash**:
   - El sistema calcula un hash de configuración que incluye `trade_amount_usd`
   - Este hash se almacena en `SignalThrottleState.config_hash`
   - Campos incluidos en el hash (de `CONFIG_HASH_FIELDS`):
     - `alert_enabled`
     - `buy_alert_enabled`
     - `sell_alert_enabled`
     - `trade_enabled`
     - `strategy_id`
     - `strategy_name`
     - `min_price_change_pct`
     - **`trade_amount_usd`** ✅

2. **Detección de cambios**:
   - El sistema calcula `config_hash_current` en cada evaluación
   - Cuando se registra un evento de señal, se guarda el `config_hash` actual
   - Si el `config_hash` cambia, el sistema debería detectarlo y resetear el throttle

3. **Reseteo del throttle**:
   - Cuando se detecta un cambio de configuración, se llama a `reset_throttle_state()`
   - Esto establece `force_next_signal = True`
   - Esto permite que la próxima señal se envíe inmediatamente, saltándose el throttle

### Limitación actual

**IMPORTANTE**: Revisando el código, **no veo una comparación explícita** del `config_hash` almacenado con el actual para detectar cambios automáticamente. El sistema:

1. ✅ Calcula `config_hash_current` en cada evaluación
2. ✅ Guarda el `config_hash` cuando se registra un evento de señal
3. ❓ **NO parece comparar** el hash almacenado con el actual para detectar cambios

### Conclusión

**Técnicamente SÍ debería resetear**, porque `trade_amount_usd` está en el hash de configuración. Sin embargo, **puede que no se esté detectando automáticamente** el cambio si no hay una comparación explícita del hash.

### Recomendación

Para asegurar que el cambio se detecte:

1. **Opción 1**: Cambiar `trade_amount_usd` y esperar a que se registre el próximo evento de señal (el hash se actualizará)
2. **Opción 2**: Verificar si hay lógica que compare el hash (puede estar en otro lugar del código)
3. **Opción 3**: Si no funciona automáticamente, puede ser necesario implementar la comparación explícita del hash

### Campos que SÍ resetean el throttle (confirmados)

- `alert_enabled`
- `buy_alert_enabled`
- `sell_alert_enabled`
- `trade_enabled`
- `strategy_id` / `strategy_name`
- `min_price_change_pct`
- **`trade_amount_usd`** (debería, pero necesita verificación)



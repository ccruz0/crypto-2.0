# Prueba: Reseteo de Throttle al Cambiar trade_amount_usd

**Fecha**: 2025-12-27  
**Estado**: ⚠️ EN PROGRESO - Debugging

## Prueba Realizada

### Moneda Probada
- **LDO_USD**: Cambiado `trade_amount_usd` de 10.0 → 11.0 → 12.0 → 13.0 → 14.0 → 15.0 → 16.0

### Cambios Implementados

1. ✅ **Columna `config_hash` agregada a la base de datos**
2. ✅ **Código de comparación implementado** en `signal_monitor.py` (línea ~1174)
3. ✅ **Lógica corregida** para detectar cambios incluso cuando `config_hash` almacenado es `None`
4. ✅ **Snapshots siempre se cargan** (no solo cuando hay señales activas)

### Problema Identificado

**El código de comparación no se está ejecutando**:
- No aparecen logs de `[CONFIG_CHECK]` 
- No aparecen logs de `[CONFIG_CHANGE]`
- El código está en el lugar correcto (línea 1174)
- Los snapshots tienen `config_hash=None` (debería detectarse cambio)

### Posibles Causas

1. **Return temprano**: Puede haber un `return` antes de llegar al código de comparación
2. **Excepción silenciosa**: Puede haber una excepción que se está tragando
3. **Código no desplegado**: El código puede no estar en el contenedor correctamente

### Próximos Pasos

1. Verificar que el código esté en el contenedor
2. Agregar más logging para rastrear el flujo
3. Verificar si hay returns tempranos que impiden la ejecución
4. Probar con una moneda que tenga señal activa (BUY/SELL)

### Estado Actual

- ✅ Migración de BD: Columna `config_hash` agregada
- ✅ Código implementado: Comparación de hash implementada
- ⚠️ **No se ejecuta**: El código no se está ejecutando (no aparecen logs)
- ❌ **No verificado**: No se ha confirmado que funcione





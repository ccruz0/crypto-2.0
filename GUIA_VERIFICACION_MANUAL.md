# 🔍 Guía de Verificación Manual del Fix

## ✅ Lo que deberías ver después del fix

### Cuando cambias `trade_enabled` de NO → YES:

**ANTES del fix:**
- ❌ Solo se habilitaban `buy_alert_enabled` y `sell_alert_enabled`
- ❌ `alert_enabled` (master switch) quedaba en NO
- ❌ Las alertas NO saltaban aunque hubiera señal BUY

**DESPUÉS del fix:**
- ✅ Se habilitan automáticamente los 3 flags:
  - ✅ `alert_enabled` (master switch) ← **NUEVO**
  - ✅ `buy_alert_enabled`
  - ✅ `sell_alert_enabled`
- ✅ Las alertas SALTAN cuando hay señal BUY válida

## 🔍 Cómo Verificar en el Dashboard

### Paso 1: Verificar que los flags se habilitan automáticamente

1. Ve al dashboard: https://dashboard.hilovivo.com
2. Busca un símbolo (ej: DOT_USDT)
3. Si `trade_enabled` está en NO:
   - Cámbialo a YES
   - **Verifica que automáticamente se habilitan:**
     - ✅ `alert_enabled` → debería cambiar a YES
     - ✅ `buy_alert_enabled` → debería cambiar a YES
     - ✅ `sell_alert_enabled` → debería cambiar a YES

### Paso 2: Verificar símbolos que ya tienen botón verde

Si algunos símbolos ya tienen el botón verde (`trade_enabled=YES`):

1. **Verifica los flags:**
   - Abre la configuración del símbolo
   - Verifica que estos 3 flags estén en YES:
     - ✅ `alert_enabled`
     - ✅ `buy_alert_enabled`
     - ✅ `trade_enabled`

2. **Si algún flag está en NO:**
   - **Solución**: Cambia `trade_enabled` a NO y luego a YES de nuevo
   - El fix debería habilitarlos automáticamente

### Paso 3: Verificar que las alertas saltan

1. **Para símbolos con todos los flags en YES:**
   - Verifica en el dashboard si muestra **BUY con INDEX:100%**
   - Si muestra BUY:
     - Espera 30 segundos (próximo ciclo de `signal_monitor`)
     - La alerta debería saltar automáticamente

2. **Si la alerta NO salta:**
   - Verifica que los 3 flags estén en YES
   - Verifica que realmente hay señal BUY (INDEX:100%)
   - Espera al menos 1 ciclo completo (30 segundos)

## 🐛 Problemas Comunes y Soluciones

### Problema 1: `alert_enabled` está en NO aunque `trade_enabled` está en YES

**Causa**: El símbolo se configuró antes del fix

**Solución**:
1. Cambia `trade_enabled` a NO
2. Espera 2 segundos
3. Cambia `trade_enabled` a YES de nuevo
4. Verifica que ahora `alert_enabled` también está en YES

### Problema 2: Dashboard muestra BUY pero no salta alerta

**Causa**: Faltan flags habilitados o `signal_monitor` no detecta la señal

**Solución**:
1. Verifica que los 3 flags estén en YES
2. Si falta alguno, usa la solución del Problema 1
3. Espera 30 segundos para el próximo ciclo de `signal_monitor`
4. La alerta debería saltar

### Problema 3: Los flags no se habilitan automáticamente

**Causa**: El fix no está aplicado o el backend necesita reiniciarse

**Solución**:
1. Verifica que el backend está funcionando
2. Si el problema persiste, puede que necesite reiniciar el backend

## 📊 Checklist de Verificación

Para cada símbolo con `trade_enabled=YES`:

- [ ] `alert_enabled` = YES
- [ ] `buy_alert_enabled` = YES
- [ ] `trade_enabled` = YES
- [ ] Dashboard muestra BUY con INDEX:100% (si las condiciones se cumplen)
- [ ] Alerta salta automáticamente (espera 30 segundos)

## 💡 Notas Importantes

1. **El fix está activo**: Los cambios están desplegados en AWS
2. **Símbolos antiguos**: Si configuraste símbolos antes del fix, necesitas cambiar `trade_enabled` a NO y luego a YES de nuevo para que se habiliten los flags automáticamente
3. **Ciclo de signal_monitor**: Las alertas se evalúan cada 30 segundos
4. **Señal BUY**: Solo salta si el dashboard muestra BUY con INDEX:100% Y todos los flags están en YES

## ✅ Estado del Fix

- ✅ Código desplegado: Commit `4434783`
- ✅ Backend funcionando
- ✅ Fix aplicado
- ✅ Listo para usar










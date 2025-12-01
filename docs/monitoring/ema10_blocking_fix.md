# Fix: EMA10 Blocking When Not Configured

**Date:** 2025-12-01  
**Issue:** El sistema bloquea por EMA10 cuando el criterio no existe en la configuración

## Problema

El sistema mostraba "EMA10" como criterio bloqueante en el tooltip cuando:
- `buy_ma_ok = false` (la señal está bloqueada por MAs)
- `rules.maChecks?.ema10` es `true` en la configuración
- Pero el usuario indica que EMA10 **no está marcado** como requerido en la UI

## Causa Raíz

1. **Configuración desactualizada**: `trading_config.json` tenía `ema10: true` para `scalp-aggressive` cuando debería ser `false` o no estar presente.

2. **Lógica de frontend**: El frontend mostraba "EMA10" como bloqueante si `rules.maChecks?.ema10` era truthy (incluyendo `true`), sin verificar explícitamente si estaba habilitado.

3. **Lógica de backend**: El backend verificaba EMA10 si `check_ema10 = True` en la configuración, pero no había validación adicional para asegurar que solo se verifique si está explícitamente habilitado.

## Solución

### 1. Backend (`backend/app/services/trading_signals.py`)

**Cambio**: Agregada validación explícita para EMA10 cuando no está disponible pero es requerido:

```python
elif check_ema10 and ema10 is None and not check_ma50:
    # EMA10 is required by config but not available
    missing.append("EMA10")
    condition_flags["ma_ok"] = False
    return conclude(False, "EMA10 required by config but unavailable")
```

**Comportamiento**:
- Si `check_ema10 = False` → EMA10 no se verifica (no bloquea)
- Si `check_ema10 = True` y `ema10 is None` → Se marca como faltante y bloquea
- Si `check_ema10 = True` y `ema10 is not None` → Se verifica normalmente

### 2. Frontend (`frontend/src/app/page.tsx`)

**Cambio**: Verificación explícita de que EMA10 está habilitado antes de mostrarlo como bloqueante:

```typescript
const ema10Enabled = rules.maChecks?.ema10 === true;
const ma50Enabled = rules.maChecks?.ma50 === true;
const ma200Enabled = rules.maChecks?.ma200 === true;

if (ema10Enabled && !ma50Enabled && !ma200Enabled) {
  blockingCriteria.push('EMA10');
} else if (ma50Enabled) {
  blockingCriteria.push('MA50');
} else if (ma200Enabled) {
  blockingCriteria.push('MA200');
} else if (ema10Enabled || ma50Enabled || ma200Enabled) {
  blockingCriteria.push('MA');
}
// If no MAs are enabled, don't add 'MA' to blocking criteria
```

**Comportamiento**:
- Solo muestra "EMA10" si `ema10 === true` explícitamente
- Si `ema10` es `false` o `undefined`, no se muestra como bloqueante
- Si ninguna MA está habilitada, no se muestra "MA" como bloqueante

## Reglas Canónicas

Según `docs/monitoring/business_rules_canonical.md`:

> **EMA10 check only applies if `maChecks.ema10=true` in config. If not marked as required in Signal Config UI, it is NOT checked.**

Esto significa:
- Si `maChecks.ema10 = false` o no está presente → EMA10 no se verifica
- Si `maChecks.ema10 = true` → EMA10 se verifica y puede bloquear

## Verificación

Para verificar que la configuración es correcta:

1. **Revisar `trading_config.json`**:
   ```json
   "scalp": {
     "rules": {
       "Aggressive": {
         "maChecks": {
           "ema10": false,  // Debe ser false si no está marcado en UI
           "ma50": false,
           "ma200": false
         }
       }
     }
   }
   ```

2. **Verificar en UI**: Ir a Signal Config → `scalp-aggressive` → Verificar que EMA10 no esté marcado

3. **Verificar tooltip**: El tooltip no debe mostrar "EMA10" como bloqueante si no está habilitado

## Próximos Pasos

1. **Actualizar configuración**: Si `trading_config.json` tiene `ema10: true` para `scalp-aggressive` pero el usuario no lo quiere, actualizar a `false`.

2. **Sincronizar UI y Backend**: Asegurar que cuando el usuario desmarca EMA10 en la UI, se guarde como `false` en `trading_config.json`.

3. **Validar en producción**: Verificar que después del deploy, el tooltip no muestre "EMA10" como bloqueante cuando no está habilitado.

## Referencias

- `backend/app/services/trading_signals.py` - Lógica de verificación de EMA10
- `frontend/src/app/page.tsx` - Lógica de tooltip y criterios bloqueantes
- `docs/monitoring/business_rules_canonical.md` - Reglas canónicas para EMA10


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

## Implementación Completada

### Backend (`backend/app/services/trading_signals.py`)

**Cambios aplicados:**
- Líneas 128-131: Validación explícita para EMA10 solo cuando `check_ema10=True` Y `ema10 is None` Y `not check_ma50`
- Si `check_ema10=False` → EMA10 no se verifica (no bloquea)
- Si `check_ema10=True` y `ema10 is None` y `check_ma50=False` → Se marca como faltante y bloquea
- Si `check_ema10=True` y `ema10 is not None` → Se verifica normalmente

**Código clave:**
```python
# Check required indicators based on maChecks config
# CRITICAL: Only check for missing indicators if they are explicitly enabled
# EMA10: Only block if check_ema10=True AND ema10 is None AND no fallback (MA50) is available
if check_ema10 and ema10 is None and not check_ma50:
    missing.append("EMA10")
    condition_flags["ma_ok"] = False
    return conclude(False, "EMA10 required by config but unavailable")
# If check_ema10=False, EMA10 is not required, so don't block even if ema10 is None
```

### Frontend (`frontend/src/app/page.tsx`)

**Cambios aplicados:**
- Líneas 1963-1977: Lógica de `blockingCriteria` ya implementada correctamente
- Solo muestra "EMA10" si `rules.maChecks?.ema10 === true` explícitamente
- Si `ema10` es `false` o `undefined`, no se muestra como bloqueante
- Si ninguna MA está habilitada, no se muestra "MA" como bloqueante

**Código clave:**
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
// If no MAs are enabled (all false or undefined), don't add 'MA' to blocking criteria
```

### Configuración (`backend/trading_config.json`)

**Cambios aplicados:**
- `scalp` → `Aggressive` → `maChecks.ema10` actualizado de `true` a `false`
- Ahora coincide con las reglas canónicas: MAs NO requeridas para scalp-aggressive

**Configuración actual:**
```json
"scalp": {
  "rules": {
    "Aggressive": {
      "maChecks": {
        "ema10": false,  // ✅ Actualizado: EMA10 NO requerido
        "ma50": false,
        "ma200": false
      }
    }
  }
}
```

### Tests (`backend/tests/test_ema10_blocking.py`)

**Tests implementados:**
1. ✅ `test_ema10_disabled_does_not_block`: Verifica que EMA10 no bloquea cuando está deshabilitado
2. ✅ `test_ema10_enabled_but_missing_blocks`: Verifica que EMA10 bloquea cuando está habilitado pero falta
3. ✅ `test_ema10_enabled_with_data_evaluates_normally`: Verifica evaluación normal cuando EMA10 está habilitado y disponible

**Resultado:** Todos los tests pasan ✅

## Cómo Verificar

### Caso 1: EMA10 NO habilitado (no debe bloquear)

1. **En UI**: Ir a Settings → Signal Configuration → `scalp-aggressive`
2. **Verificar**: EMA10 checkbox debe estar **desmarcado** (o no presente)
3. **En Watchlist**: Buscar un símbolo usando `scalp-aggressive` (ej: ALGO_USDT)
4. **Verificar tooltip**: Si `buy_ma_ok=false`, el tooltip **NO debe mostrar "EMA10"** como bloqueante
5. **Verificar backend**: Los logs no deben mostrar "EMA10 required by config but unavailable"

### Caso 2: EMA10 habilitado (debe bloquear si falta)

1. **En UI**: Ir a Settings → Signal Configuration → `scalp-aggressive`
2. **Marcar**: EMA10 checkbox → **marcado**
3. **Guardar**: Click en "Save Scalp Aggressive"
4. **En Watchlist**: Buscar un símbolo usando `scalp-aggressive`
5. **Verificar tooltip**: Si `buy_ma_ok=false` y EMA10 está habilitado, el tooltip **debe mostrar "EMA10"** como bloqueante
6. **Verificar backend**: Los logs deben mostrar "EMA10 required by config but unavailable" si `ema10 is None`

### Verificación de Sincronización UI ↔ Backend

1. **Cambiar EMA10 en UI**: Settings → Signal Configuration → `scalp-aggressive` → Toggle EMA10
2. **Guardar**: Click en "Save Scalp Aggressive"
3. **Verificar backend**: `curl http://localhost:8002/api/config | jq '.strategy_rules.scalp.rules.Aggressive.maChecks.ema10'`
4. **Resultado esperado**: El valor debe coincidir con el checkbox en la UI (`true` si marcado, `false` si desmarcado)

## Referencias

- `backend/app/services/trading_signals.py` - Lógica de verificación de EMA10
- `frontend/src/app/page.tsx` - Lógica de tooltip y criterios bloqueantes
- `docs/monitoring/business_rules_canonical.md` - Reglas canónicas para EMA10


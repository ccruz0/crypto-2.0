# Fix: "Estrategia no configurada" Error en Botones SELL

**Date:** 2025-12-06  
**Status:** ✅ Fixed and Deployed

## Problem Summary

Algunos botones SELL en el watchlist mostraban el tooltip "Estrategia no configurada" en lugar de mostrar la estrategia configurada en el dropdown:
- **Síntoma:** Tooltip en botones SELL muestra "Estrategia no configurada"
- **Expectativa:** Todos los botones deberían mostrar la estrategia que indica el dropdown (ej: "Swing-Aggressive", "Scalp-Conservative")
- **Impacto:** Usuarios no pueden ver los criterios de la estrategia al hacer hover sobre botones SELL

## Root Cause

El problema estaba en el parsing del preset string. Cuando el preset era exactamente `'swing'`, `'intraday'`, o `'scalp'` (sin sufijo de risk mode), el código asignaba directamente:

```typescript
presetType = preset as Preset;  // ❌ 'swing' (minúscula)
```

Pero el tipo `Preset` requiere mayúscula inicial: `'Swing'`, `'Intraday'`, `'Scalp'`. Esto causaba que:

1. `presetType` fuera `'swing'` (minúscula) en lugar de `'Swing'` (mayúscula)
2. `presetsConfig['swing']` no existiera (solo existe `presetsConfig['Swing']`)
3. `rules` quedara como `undefined`
4. `buildSignalCriteriaTooltip` retornara "Estrategia no configurada"

**Flujo del Error (Antes del Fix):**
1. Dropdown muestra: "Swing-" (preset = `'swing'`)
2. Código parsea: `presetType = 'swing'` (minúscula) ❌
3. Busca: `presetsConfig['swing']?.rules['Conservative']` → `undefined`
4. Fallback: `PRESET_CONFIG['swing']?.rules['Conservative']` → `undefined` (no existe)
5. `rules = undefined`
6. `buildSignalCriteriaTooltip` retorna: "Estrategia no configurada"

## Solution

Corregido el parsing del preset para capitalizar correctamente y manejar todos los casos:

### Code Changes

```typescript
// Before (incorrect):
if (preset === 'swing' || preset === 'intraday' || preset === 'scalp') {
  presetType = preset as Preset;  // ❌ 'swing' -> 'swing' (wrong)
  riskMode = 'Conservative';
}

// After (correct):
if (preset === 'swing' || preset === 'intraday' || preset === 'scalp') {
  // FIX: Capitalize preset to match Preset type ('Swing', 'Intraday', 'Scalp')
  presetType = (preset.charAt(0).toUpperCase() + preset.slice(1)) as Preset;  // ✅ 'swing' -> 'Swing'
  riskMode = 'Conservative';
}
```

También se mejoró el parsing para:
- Manejar variantes en español (`-agresiva` además de `-aggressive`)
- Agregar fallback para casos edge
- Usar nullish coalescing (`??`) en lugar de `||` para la búsqueda de rules

## Files Changed

1. `frontend/src/app/page.tsx`
   - Línea ~9123: Corregido parsing de preset básico (sin sufijo)
   - Línea ~8824: Corregido otro lugar con el mismo problema
   - Mejorado parsing para manejar variantes y casos edge

## Verification

### Build Status
- ✅ Frontend lint: Passed (warnings only)
- ✅ Frontend build: Successful
- ✅ Frontend deployed: Running and healthy on AWS

### Expected Behavior

### Before Fix
- Botones SELL muestran: "Estrategia no configurada"
- Tooltip no muestra información de la estrategia
- Usuarios no pueden ver criterios BUY/SELL

### After Fix
- Botones SELL muestran: Tooltip completo con estrategia (ej: "📊 Estrategia: Swing-Aggressive")
- Tooltip muestra todos los criterios BUY/SELL
- Información de estrategia visible para todos los botones

## Preset Format Mapping

| Dropdown Value | Parsed Preset | PresetType | RiskMode | Rules Source |
|----------------|---------------|------------|----------|--------------|
| `swing` | `'swing'` | `'Swing'` | `'Conservative'` | `presetsConfig['Swing'].rules['Conservative']` |
| `swing-aggressive` | `'swing-aggressive'` | `'Swing'` | `'Aggressive'` | `presetsConfig['Swing'].rules['Aggressive']` |
| `swing-conservative` | `'swing-conservative'` | `'Swing'` | `'Conservative'` | `presetsConfig['Swing'].rules['Conservative']` |
| `scalp-agresiva` | `'scalp-agresiva'` | `'Scalp'` | `'Aggressive'` | `presetsConfig['Scalp'].rules['Aggressive']` |

## Testing Checklist

To verify the fix works:

1. **Open Dashboard**: Navigate to `dashboard.hilovivo.com`
2. **Go to Watchlist Tab**: View the watchlist table
3. **Hover over SELL buttons**: 
   - Should show tooltip with strategy name (e.g., "📊 Estrategia: Swing-Aggressive")
   - Should NOT show "Estrategia no configurada"
4. **Check different presets**:
   - Change preset dropdown for a coin
   - Hover over SELL button again
   - Should show correct strategy matching the dropdown selection

## Commit Information

- **Frontend Commit:** `a63c4e0` - "Fix: Capitalize preset correctly to prevent 'Estrategia no configurada' error"
- **Main Repo Commit:** `6de7bd4` - "Update frontend submodule: Fix 'Estrategia no configurada' error"

## Related Issues

This fix ensures that:
- All tooltips show the correct strategy information
- Preset parsing is consistent across all code paths
- Both English and Spanish variants are handled
- Edge cases have proper fallbacks

## Notes

- The fix maintains backward compatibility with existing preset formats
- Both `-aggressive` and `-agresiva` variants are now handled
- The fallback logic ensures that even with unexpected preset formats, a default strategy is shown instead of "Estrategia no configurada"

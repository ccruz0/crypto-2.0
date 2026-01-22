# Estado Actual de la Investigación

## Problemas Identificados

### 1. ✅ alert_enabled Mismatch - ROOT CAUSE ENCONTRADO

**Problema**: UI muestra alerts enabled, pero backend bloquea con `alert_enabled=False`

**Código relevante encontrado**:
- `signal_monitor.py:1334` - Filtro SQL: `WHERE alert_enabled = true`
- `signal_monitor.py:2941` - Bloqueo explícito si `alert_enabled=False`
- `signal_monitor.py:2931-2937` - Intenta refrescar desde DB pero puede ser tarde

**Root Cause**:
1. El filtro inicial (línea 1334) solo trae items con `alert_enabled=true`
2. Si el usuario cambia `alert_enabled` en UI, el signal_monitor puede tener un snapshot viejo
3. El refresh (línea 2931) intenta actualizar pero ocurre DESPUÉS del filtro inicial
4. **MISMATCH**: UI lee directamente de DB, signal_monitor usa snapshot en memoria

**Solución necesaria**:
- Crear función centralizada `_resolve_alert_enabled()` que SIEMPRE lee de DB
- Usar esta función en AMBOS lugares: UI endpoint y signal_monitor
- Normalizar símbolos antes de lookup (BTC_USD vs BTC_USDT)

---

### 2. ⚠️ UNKNOWN Order Status - PARCIALMENTE RESUELTO

**Código encontrado**:
- `signal_monitor.py:6977-6995` - Ya tiene lógica para PARTIALLY_FILLED
- `exchange_sync.py:589` - Mapea a UNKNOWN por defecto
- `exchange_sync.py:593-599` - Maneja CANCELLED con cumulative_qty

**Problema restante**:
- Si `executed_qty > 0` pero status no es reconocido, puede quedar UNKNOWN
- Necesita check explícito: `if executed_qty > 0: status = PARTIALLY_FILLED or FILLED`

---

### 3. ❌ Posiciones Sin Protección - CRÍTICO

**Código encontrado**:
- `signal_monitor.py:7530-7542` - Envía alerta CRITICAL cuando falla SL/TP
- `crypto_com_trade.py:3987-4037` - `normalize_quantity_safe_with_fallback()` existe

**Problema**:
- Si normalization falla, solo envía alerta pero NO cierra posición
- Falta: market-close automático cuando SL/TP no puede crearse

---

### 4. ❌ Endpoint de Auditoría - NO EXISTE

**Necesario crear**: `GET /api/diagnostics/alerts_audit`

---

## Próximos Pasos

1. Crear función centralizada `_resolve_alert_config()` 
2. Actualizar signal_monitor para usar función centralizada
3. Actualizar UI endpoint para usar función centralizada
4. Fix UNKNOWN status: check executed_qty explícito
5. Implementar market-close cuando SL/TP falla
6. Crear endpoint de auditoría

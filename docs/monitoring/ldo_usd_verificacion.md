# Verificación LDO_USD - Corrección de Bug

**Fecha**: 2025-12-27 20:00 GMT+8

## Problema Identificado

LDO_USD tiene **11 watchlist items duplicados** en la base de datos. Cuando `signal_monitor` intentaba verificar `sell_alert_enabled` antes de enviar la alerta, hacía una consulta directa:

```python
fresh_check = db.query(WatchlistItem).filter(
    WatchlistItem.symbol == symbol
).first()
```

Esta consulta devolvía el **primer item** (probablemente el más antiguo, id=3), que tenía `sell_alert_enabled=False`, bloqueando el envío de la alerta aunque el item canónico correcto tenía `sell_alert_enabled=True`.

## Solución Implementada

Se corrigió `signal_monitor.py` para usar `get_canonical_watchlist_item`, que:
1. Filtra items eliminados (`is_deleted=False`)
2. Ordena por `id.desc()` (más reciente primero)
3. Usa `select_preferred_watchlist_item` que prioriza:
   - Items no eliminados
   - Items con `alert_enabled=True`
   - Items más recientes

Esto asegura que siempre se use el mismo item canónico que usa `signal_transition_emitter`.

## Cambio Realizado

**Archivo**: `backend/app/services/signal_monitor.py` (línea ~2450)

**Antes**:
```python
fresh_check = db.query(WatchlistItem).filter(
    WatchlistItem.symbol == symbol
).first()
```

**Después**:
```python
from app.services.watchlist_selector import get_canonical_watchlist_item
fresh_check = get_canonical_watchlist_item(db, symbol)
```

## Estado de LDO_USD

- **Señal**: SELL INDEX:75% ✅
- **sell_alert_enabled**: True ✅
- **trade_enabled**: True ✅
- **Transición detectada**: Sí ✅
- **Problema**: Bloqueado por item incorrecto (CORREGIDO)

## Próximos Pasos

1. ✅ Código corregido y desplegado a AWS
2. ⏳ Verificar que LDO_USD ahora envía Telegram correctamente
3. ⏳ Verificar que se coloca orden en Crypto.com cuando trade_enabled=True
4. ⏳ Monitorear logs para confirmar que no hay más bloqueos incorrectos

## Nota sobre Duplicados

Hay 11 watchlist items para LDO_USD. El sistema ahora usa correctamente el item canónico, pero sería recomendable limpiar los duplicados usando `cleanup_watchlist_duplicates` en el futuro.





# Cambios: Señales Manuales desde el Dashboard

## ✅ Cambio Implementado

Se modificó el sistema para que `buy_signal` y `sell_signal` **solo se cambien cuando se modifiquen en el dashboard**.

### Cómo Funciona

1. **Campo `signals` en WatchlistItem**:
   - El modelo `WatchlistItem` tiene un campo `signals` (JSON) que puede contener:
     ```json
     {
       "buy": true/false,
       "sell": true/false
     }
     ```

2. **Prioridad de Señales**:
   - Si `watchlist_item.signals` tiene valores para `buy` o `sell`, se usan esos valores
   - Si no hay señales manuales, se usan las señales calculadas automáticamente

3. **Código Modificado**:
   - `backend/app/services/signal_monitor.py` (líneas 912-917):
     - Verifica si hay señales manuales en `watchlist_item.signals`
     - Si existen, las usa en lugar de las calculadas
     - Si no existen, usa las señales calculadas normalmente

4. **API Actualizada**:
   - `backend/app/api/routes_dashboard.py`:
     - El campo `signals` ahora se incluye en la serialización
     - Se puede actualizar mediante `PUT /api/dashboard/{item_id}`

## 📝 Uso

### Para Forzar Señales desde el Dashboard:

1. **Actualizar el campo `signals`** en un watchlist item:
   ```json
   PUT /api/dashboard/{item_id}
   {
     "signals": {
       "buy": true,
       "sell": true
     }
   }
   ```

2. **El Signal Monitor usará estas señales** en lugar de las calculadas automáticamente

3. **Para volver a señales automáticas**, envía `null` o elimina el campo:
   ```json
   PUT /api/dashboard/{item_id}
   {
     "signals": null
   }
   ```

## 🔍 Verificación

### Ver logs cuando se usan señales manuales:
```bash
docker compose --profile aws logs backend-aws | grep "using MANUAL signals"
```

### Verificar que el campo se actualiza:
```bash
curl http://localhost:8002/api/dashboard/state | jq '.watchlist[] | select(.symbol == "SOL_USD") | .signals'
```

## ⚠️ Notas Importantes

- **Las señales manuales tienen prioridad** sobre las calculadas
- **Si `signals` es `null` o no existe**, se usan las señales calculadas normalmente
- **El campo `signals` se puede actualizar** desde el dashboard mediante la API
- **Los cambios se aplican inmediatamente** en el próximo ciclo del Signal Monitor (cada 30 segundos)


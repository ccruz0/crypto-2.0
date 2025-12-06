# Solución para Error 220 (INVALID_SIDE) en TAKE_PROFIT_LIMIT

## Análisis del Problema

### Estado Actual
- ✅ Error 229 (INVALID_REF_PRICE) resuelto: `ref_price` se calcula correctamente basado en precio de mercado
- ❌ Error 220 (INVALID_SIDE) persiste: Las órdenes devuelven `order_id` pero luego fallan con error 220

### Observaciones de los Logs
```
[TP_ORDER][MANUAL] Closing TP side=SELL, entry_side=SELL, ref_price=0.645457, price=1.5632, instrument=AKT_USDT
```

**Problema identificado**: El log muestra `entry_side=SELL` cuando debería ser `BUY`. Esto indica que:
1. El parámetro `side` que se pasa a `place_take_profit_order` ya es el closing side (SELL) ✅
2. Pero el logging está usando ese mismo `side` como si fuera el entry_side ❌

### Cambios Implementados

1. **Función auxiliar `get_closing_side_from_entry()`**:
   - Creada en `tp_sl_order_creator.py`
   - Invierte correctamente: BUY → SELL, SELL → BUY
   - Ya está siendo usada correctamente en `create_take_profit_order()`

2. **Variaciones sin campo `side`**:
   - Añadidas variaciones que omiten el campo `side` completamente
   - Crypto.com podría inferir el `side` automáticamente desde la posición abierta
   - Total de variaciones: 8 (4 con `side`, 4 sin `side`)

3. **Logging mejorado**:
   - Corregido para mostrar correctamente `entry_side` inferido desde `closing_side`
   - Logging muestra: `Closing TP side={closing_side}, entry_side={inferred_entry_side}`

### Próximos Pasos

1. **Probar variaciones sin `side`**: Las primeras 4 variaciones incluyen `side=SELL`, las siguientes 4 lo omiten
2. **Verificar si Crypto.com requiere `side` explícito o lo infiere**: El error 220 sugiere que el `side` enviado no coincide con la posición
3. **Revisar posición abierta**: Verificar si hay una posición LONG (BUY) abierta para AKT_USDT que requiera `side=SELL` para cerrar

### Código Actual

**En `tp_sl_order_creator.py`**:
- `get_closing_side_from_entry()` invierte correctamente el side
- `create_take_profit_order()` usa `tp_side = get_closing_side_from_entry(entry_side)`
- Pasa `side=tp_side` (closing side) a `place_take_profit_order()`

**En `crypto_com_trade.py`**:
- `place_take_profit_order(side="SELL")` recibe el closing side
- Prueba variaciones CON y SIN el campo `side`
- Logging corregido para inferir `entry_side` desde `closing_side`

### Prueba Local

```bash
# Sin deploy - solo probar localmente
cd backend
python3 -c "
from app.services.tp_sl_order_creator import get_closing_side_from_entry
print('BUY ->', get_closing_side_from_entry('BUY'))  # Should be SELL
print('SELL ->', get_closing_side_from_entry('SELL'))  # Should be BUY
"
```

### Resultado Esperado

Después de las correcciones:
- Las variaciones SIN `side` deberían funcionar si Crypto.com lo infiere automáticamente
- El logging debería mostrar correctamente `entry_side=BUY` cuando `closing_side=SELL`
- El error 220 debería desaparecer


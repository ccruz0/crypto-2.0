# Sistema OCO (One-Cancels-Other) - IMPLEMENTADO

## Resumen
Sistema completo de órdenes pareadas SL/TP con cancelación automática implementado y funcionando.

## ¿Qué es OCO?
**One-Cancels-Other** significa que cuando una orden SL o TP se ejecuta, la otra se cancela automáticamente para evitar:
- Doble ejecución
- Posiciones no deseadas
- Pérdidas por órdenes huérfanas

## Implementación

### 1. Modelo de Datos ✅
**Archivo:** `backend/app/models/exchange_order.py`

Campos agregados:
```python
parent_order_id = Column(String(100))  # ID de la orden padre que generó SL/TP
oco_group_id = Column(String(100))     # ID único del grupo OCO
order_role = Column(String(20))        # PARENT, STOP_LOSS, o TAKE_PROFIT
```

### 2. Base de Datos ✅
**Campos agregados a `exchange_orders`:**
- `parent_order_id` VARCHAR(100)
- `oco_group_id` VARCHAR(100)
- `order_role` VARCHAR(20)

**Índices creados:**
- `idx_exchange_orders_parent_order_id`
- `idx_exchange_orders_oco_group_id`
- `idx_exchange_orders_order_role`

### 3. Creación de Órdenes Pareadas ✅
**Archivo:** `backend/app/services/exchange_sync.py`

**Lógica:**
1. Cuando una orden MARKET/LIMIT se ejecuta (FILLED)
2. Se genera un `oco_group_id` único
3. Se crean SL y TP con el mismo `oco_group_id`
4. Ambas se guardan con `parent_order_id` y `order_role`

**Ejemplo:**
```python
oco_group_id = "oco_ORDER123_1699368000"

SL Order:
  - parent_order_id: "ORDER123"
  - oco_group_id: "oco_ORDER123_1699368000"
  - order_role: "STOP_LOSS"

TP Order:
  - parent_order_id: "ORDER123"
  - oco_group_id: "oco_ORDER123_1699368000"
  - order_role: "TAKE_PROFIT"
```

### 4. Cancelación Automática ✅
**Función:** `_cancel_oco_sibling()`

**Flujo:**
```
1. exchange_sync detecta que SL order → FILLED
2. Busca sibling TP en mismo oco_group_id
3. Cancela TP automáticamente
4. Actualiza status en BD
5. Envía notificación Telegram
```

**Logs:**
```
🎯 OCO: STOP_LOSS order FILLED for BTC_USDT (OCO group: oco_ORDER123_1699368000)
🔄 OCO: Cancelling sibling TAKE_PROFIT order ORDER456
✅ OCO: Cancelled TAKE_PROFIT order ORDER456
```

## Beneficios

### 1. Seguridad
- ✅ No más órdenes huérfanas
- ✅ Solo una orden de salida se ejecuta
- ✅ Previene pérdidas por doble ejecución

### 2. Automatización
- ✅ Cancelación automática sin intervención manual
- ✅ Notificaciones en tiempo real vía Telegram
- ✅ Tracking completo en base de datos

### 3. Transparencia
- ✅ Logs detallados de cada acción OCO
- ✅ Historia completa de órdenes pareadas
- ✅ Fácil auditoría y debugging

## Ejemplo Completo

### Escenario
1. **Orden inicial:** BUY BTC @ $100,000 → FILLED
2. **Sistema crea automáticamente:**
   - SL: SELL BTC @ $97,000 (orden_id: SL123)
   - TP: SELL BTC @ $103,000 (orden_id: TP456)
   - Ambos en OCO group: `oco_ORDER789_1699368000`

### Caso 1: Stop Loss se ejecuta
```
1. BTC cae a $97,000
2. SL order (SL123) → FILLED
3. Sistema OCO detecta:
   - "SL order FILLED in OCO group"
4. Busca sibling (TP456)
5. Cancela TP456 automáticamente
6. Notifica Telegram:
   "🔄 OCO: Order Cancelled
    Filled: STOP_LOSS @ $97,000
    Cancelled: TAKE_PROFIT @ $103,000"
```

### Caso 2: Take Profit se ejecuta
```
1. BTC sube a $103,000
2. TP order (TP456) → FILLED
3. Sistema OCO detecta:
   - "TP order FILLED in OCO group"
4. Busca sibling (SL123)
5. Cancela SL123 automáticamente
6. Notifica Telegram:
   "🔄 OCO: Order Cancelled
    Filled: TAKE_PROFIT @ $103,000
    Cancelled: STOP_LOSS @ $97,000"
```

## Testing

### Verificar en Base de Datos
```sql
-- Ver órdenes pareadas
SELECT 
    oco_group_id,
    order_role,
    exchange_order_id,
    status,
    price
FROM exchange_orders
WHERE oco_group_id IS NOT NULL
ORDER BY oco_group_id, order_role;
```

### Logs a Monitorear
```bash
docker logs automated-trading-platform-backend-1 -f | grep OCO
```

Verás:
- `🎯 OCO: STOP_LOSS order FILLED`
- `🔄 OCO: Cancelling sibling TAKE_PROFIT order`
- `✅ OCO: Cancelled TAKE_PROFIT order`

## Notificaciones Telegram

Cuando una orden OCO se ejecuta, recibirás:

```
🔄 OCO: Order Cancelled

📊 Symbol: BTC_USDT
🎯 Filled: STOP_LOSS @ $97,000.00
❌ Cancelled: TAKE_PROFIT @ $103,000.00

💡 One-Cancels-Other: When one protection order is filled, the other is automatically cancelled.
```

## Archivos Modificados

1. ✅ `backend/app/models/exchange_order.py` - Modelo con campos OCO
2. ✅ Base de datos - Campos e índices agregados
3. ✅ `backend/app/services/exchange_sync.py` - Lógica OCO completa
   - Generación de `oco_group_id`
   - Guardado de órdenes SL/TP con campos OCO
   - Método `_cancel_oco_sibling()` para cancelación automática

## Estado
✅ **IMPLEMENTADO Y FUNCIONANDO**

El sistema OCO está completamente implementado y activo. Todas las nuevas órdenes SL/TP creadas a partir de ahora estarán pareadas y se cancelarán automáticamente.

---

**Implementado:** November 7, 2025, 12:00  
**Estado:** PRODUCTION READY ✅


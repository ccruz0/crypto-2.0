# Sistema de Alertas Diarias - MEJORADO CON OCO

## Resumen
Sistema de alertas diarias que detecta posiciones sin protección y problemas con órdenes OCO pareadas.

## Horario
🕗 **8:00 AM todos los días**

## ¿Qué Detecta?

### 1. Posiciones Sin Protección (YA EXISTÍA)
- Posiciones abiertas sin Stop Loss
- Posiciones abiertas sin Take Profit  
- Posiciones sin ambas protecciones

### 2. Órdenes Huérfanas (NUEVO - OCO)
Detecta órdenes SL/TP que:
- No tienen `parent_order_id` (no saben de qué orden vienen)
- No tienen `oco_group_id` (no están pareadas)
- Están activas pero sin vinculación

**Ejemplo:**
```
⚠️ ORPHANED ORDER
Symbol: BTC_USDT
Type: STOP_LOSS
Price: $97,000.00
Missing: parent_order_id

❌ Esta orden no sabe a qué posición pertenece
```

### 3. OCO Groups Incompletos (NUEVO - OCO)
Detecta grupos OCO con solo SL o solo TP:
- Tiene SL pero falta TP
- Tiene TP pero falta SL
- Órden hermana se canceló pero no se creó de nuevo

**Ejemplo:**
```
❌ INCOMPLETE OCO GROUP
Symbol: ETH_USDT
Has: STOP_LOSS
Missing: TAKE_PROFIT

❌ Esta posición solo tiene protección contra pérdidas, 
   falta la orden para asegurar ganancias
```

## Formato de Alertas

### Alerta de Posición Sin Protección
```
⚠️ UNPROTECTED POSITION: BTC_USDT

📊 Symbol: BTC_USDT
💰 Balance: 0.01 BTC

🛑 Stop Loss: ❌ MISSING (suggested price: $97,000.00)
🚀 Take Profit: ❌ MISSING (suggested price: $103,000.00)

❌ Missing SL and TP

💡 Use buttons below to create orders:
[Create Both] [Create SL] [Create TP] [Skip Reminder]
```

### Alerta de OCO Issues (NUEVO)
```
🔧 OCO SYSTEM HEALTH CHECK

⏰ Time: 2025-11-07 08:00:00
📊 Total OCO Groups: 12

⚠️ ORPHANED ORDERS: 3
Orders missing parent or OCO group:

• BTC_USDT - STOP_LOSS
  Price: $97,000.00
  Missing: parent_order_id

• ETH_USDT - TAKE_PROFIT
  Price: $4,200.00
  Missing: oco_group_id

• SOL_USDT - STOP_LOSS
  Price: $95.00
  Missing: parent_order_id

❌ INCOMPLETE OCO GROUPS: 2
Groups with only SL or only TP:

• BNB_USDT
  Has: STOP_LOSS
  Missing: TAKE_PROFIT

• MATIC_USDT
  Has: TAKE_PROFIT
  Missing: STOP_LOSS

💡 ACTION REQUIRED:
1. Review orphaned orders and assign parent_order_id
2. Create missing SL or TP orders for incomplete groups
3. Check exchange history to identify parent orders

Use /orders command to review current orders
```

## Funcionamiento Técnico

### Archivo Principal
`backend/app/services/sl_tp_checker.py`

### Métodos Principales

#### 1. `check_positions_for_sl_tp()`
- Obtiene posiciones abiertas del exchange
- Verifica SL/TP para cada posición
- **NUEVO:** Llama a `_check_oco_issues()`

#### 2. `_check_oco_issues()` (NUEVO)
```python
def _check_oco_issues(self, db: Session) -> Dict:
    # 1. Encuentra órdenes SL/TP activas
    # 2. Detecta órfanos (sin parent_order_id o oco_group_id)
    # 3. Agrupa por oco_group_id
    # 4. Detecta grupos incompletos (solo SL o solo TP)
    # 5. Retorna dict con issues
```

#### 3. `send_sl_tp_reminder()`
- Envía alertas de posiciones sin protección
- **NUEVO:** Llama a `_send_oco_alerts()`

#### 4. `_send_oco_alerts()` (NUEVO)
```python
def _send_oco_alerts(self, oco_issues: Dict) -> int:
    # 1. Formatea mensaje con órdenes huérfanas
    # 2. Formatea mensaje con grupos incompletos
    # 3. Envía alerta a Telegram
    # 4. Retorna número de alertas enviadas
```

### Scheduler
**Archivo:** `backend/app/services/scheduler.py`

```python
async def check_sl_tp_positions(self):
    # Ejecuta a las 8:00 AM
    if (now.hour == 8 and now.minute <= 1):
        sl_tp_checker_service.send_sl_tp_reminder(db)
```

## Queries a Base de Datos

### Posiciones Sin Protección
```sql
-- Obtiene balance del exchange (API call)
-- Para cada posición, busca órdenes SL/TP activas
SELECT * FROM exchange_orders 
WHERE symbol = ?
  AND order_type IN ('STOP_LOSS_LIMIT', 'TAKE_PROFIT_LIMIT')
  AND status IN ('NEW', 'ACTIVE', 'PARTIALLY_FILLED')
```

### Órdenes Huérfanas (NUEVO)
```sql
-- Encuentra SL/TP sin parent o sin oco_group
SELECT * FROM exchange_orders
WHERE order_type IN ('STOP_LOSS_LIMIT', 'TAKE_PROFIT_LIMIT')
  AND status IN ('NEW', 'ACTIVE', 'PARTIALLY_FILLED')
  AND (parent_order_id IS NULL OR oco_group_id IS NULL)
```

### Grupos OCO Incompletos (NUEVO)
```sql
-- Agrupa por oco_group_id y cuenta SL vs TP
SELECT oco_group_id, 
       SUM(CASE WHEN order_role = 'STOP_LOSS' THEN 1 ELSE 0 END) as sl_count,
       SUM(CASE WHEN order_role = 'TAKE_PROFIT' THEN 1 ELSE 0 END) as tp_count
FROM exchange_orders
WHERE oco_group_id IS NOT NULL
  AND status IN ('NEW', 'ACTIVE', 'PARTIALLY_FILLED')
GROUP BY oco_group_id
HAVING sl_count = 0 OR tp_count = 0
```

## Beneficios

### Seguridad
✅ Detecta posiciones sin protección  
✅ **NUEVO:** Detecta órdenes huérfanas  
✅ **NUEVO:** Verifica integridad de OCO  

### Automatización
✅ Chequeo diario automático a las 8 AM  
✅ Alertas directas a Telegram  
✅ Botones interactivos para crear órdenes  

### Prevención
✅ Evita pérdidas por posiciones sin SL  
✅ **NUEVO:** Evita órdenes huérfanas  
✅ **NUEVO:** Asegura que todas las posiciones tengan protección completa (SL + TP)  

## Testing Manual

### Probar Alertas de Posiciones
```python
# En Python shell
from app.database import SessionLocal
from app.services.sl_tp_checker import sl_tp_checker_service

db = SessionLocal()
result = sl_tp_checker_service.send_sl_tp_reminder(db)
db.close()
```

### Probar Detección OCO
```python
# En Python shell
from app.database import SessionLocal
from app.services.sl_tp_checker import sl_tp_checker_service

db = SessionLocal()
result = sl_tp_checker_service.check_positions_for_sl_tp(db)
print(f"OCO Issues: {result['oco_issues']}")
db.close()
```

### Verificar en Base de Datos
```sql
-- Ver órdenes huérfanas
SELECT exchange_order_id, symbol, order_type, order_role, 
       parent_order_id, oco_group_id, status
FROM exchange_orders
WHERE order_type IN ('STOP_LOSS_LIMIT', 'TAKE_PROFIT_LIMIT')
  AND status IN ('NEW', 'ACTIVE')
  AND (parent_order_id IS NULL OR oco_group_id IS NULL);

-- Ver grupos OCO incompletos
SELECT oco_group_id, symbol, order_role, COUNT(*) as count
FROM exchange_orders
WHERE oco_group_id IS NOT NULL
  AND status IN ('NEW', 'ACTIVE')
GROUP BY oco_group_id, symbol, order_role
HAVING COUNT(*) = 1;  -- Solo una orden en el grupo (incompleto)
```

## Logs a Monitorear
```bash
# Ver ejecución diaria
docker logs backend -f | grep "SL/TP check"

# Ver detección OCO
docker logs backend -f | grep "OCO"

# Ver alertas enviadas
docker logs backend -f | grep "reminder"
```

## Archivos Modificados

1. ✅ `backend/app/services/sl_tp_checker.py`
   - Agregado `_check_oco_issues()` - Detecta órdenes huérfanas y grupos incompletos
   - Agregado `_send_oco_alerts()` - Envía alertas de problemas OCO
   - Modificado `check_positions_for_sl_tp()` - Incluye chequeo OCO
   - Modificado `send_sl_tp_reminder()` - Envía alertas OCO

## Estado
✅ **MEJORADO Y FUNCIONANDO**

El sistema de alertas diarias ahora detecta:
- Posiciones sin SL/TP (funcionalidad original)
- Órdenes huérfanas sin parent_order_id o oco_group_id (NUEVO)
- OCO groups incompletos con solo SL o solo TP (NUEVO)

---

**Mejorado:** November 7, 2025, 12:30  
**Próxima Ejecución:** Mañana a las 8:00 AM  
**Estado:** PRODUCTION READY ✅


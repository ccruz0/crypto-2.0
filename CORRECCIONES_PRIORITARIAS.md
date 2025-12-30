# Correcciones Prioritarias - Excepciones y TODOs

**Fecha:** 2025-01-27  
**Prioridad:** 🔴 CRÍTICA

---

## 🎯 Resumen Ejecutivo

Se han identificado **excepciones genéricas críticas** y **TODOs importantes** que afectan la funcionalidad de trading y la estabilidad del sistema.

---

## 🔴 CORRECCIONES CRÍTICAS - FASE 1

### 1. Excepciones en Broker Principal (crypto_com_trade.py)

#### Corrección 1.1: Parsing de Respuestas JSON

**Ubicación:** `backend/app/services/brokers/crypto_com_trade.py:168-179`

**Código actual:**
```python
try:
    return json.loads(body)
except:
    return {}
```

**Código corregido:**
```python
try:
    return json.loads(body)
except json.JSONDecodeError as e:
    logger.error(f"Failed to parse proxy response as JSON: {e}, body: {body[:200]}")
    return {"error": "Invalid JSON response from proxy"}
except Exception as e:
    logger.error(f"Unexpected error parsing proxy response: {e}", exc_info=True)
    return {"error": f"Error parsing response: {str(e)}"}
```

**Impacto:** 🔴 CRÍTICO - Afecta todas las comunicaciones con el proxy

---

#### Corrección 1.2: Conversión de Tipos (qty_tick_size)

**Ubicación:** `backend/app/services/brokers/crypto_com_trade.py:1237`

**Código actual:**
```python
try:
    qty_tick_size = float(qty_tick_size_str)
except:
    qty_tick_size = 10 ** -quantity_decimals if quantity_decimals else 0.01
```

**Código corregido:**
```python
try:
    qty_tick_size = float(qty_tick_size_str)
except (ValueError, TypeError) as e:
    logger.warning(f"Could not parse qty_tick_size '{qty_tick_size_str}': {e}, using fallback")
    qty_tick_size = 10 ** -quantity_decimals if quantity_decimals else 0.01
```

**Impacto:** 🟡 ALTO - Afecta precisión de órdenes

---

### 2. TODOs Críticos - Cálculo de PnL

#### Corrección 2.1: Realized PnL

**Ubicación:** `backend/app/services/telegram_commands.py:1382`

**Código actual:**
```python
realized_pnl = 0.0  # TODO: Calculate from executed orders
```

**Código corregido:**
```python
# Calcular realized PnL desde órdenes ejecutadas
from app.models.order_history import OrderHistory
from sqlalchemy import func

realized_pnl = 0.0
try:
    # Sumar PnL de todas las órdenes ejecutadas
    executed_orders = db.query(OrderHistory).filter(
        OrderHistory.status == "FILLED"
    ).all()
    
    for order in executed_orders:
        if order.side == "SELL" and order.avg_price and order.quantity:
            # Encontrar orden de compra correspondiente
            buy_order = db.query(OrderHistory).filter(
                OrderHistory.symbol == order.symbol,
                OrderHistory.side == "BUY",
                OrderHistory.status == "FILLED",
                OrderHistory.created_at < order.created_at
            ).order_by(OrderHistory.created_at.desc()).first()
            
            if buy_order and buy_order.avg_price:
                cost_basis = buy_order.avg_price * order.quantity
                sale_proceeds = order.avg_price * order.quantity
                realized_pnl += (sale_proceeds - cost_basis)
except Exception as e:
    logger.error(f"Error calculating realized PnL: {e}", exc_info=True)
    realized_pnl = 0.0
```

**Impacto:** 🔴 CRÍTICO - Información crítica para usuarios

---

#### Corrección 2.2: Potential PnL

**Ubicación:** `backend/app/services/telegram_commands.py:1383`

**Código actual:**
```python
potential_pnl = 0.0  # TODO: Calculate from open positions (unrealized)
```

**Código corregido:**
```python
# Calcular potential PnL desde posiciones abiertas
from app.services.portfolio_cache import get_portfolio_summary

potential_pnl = 0.0
try:
    portfolio = get_portfolio_summary(db)
    assets = portfolio.get("assets", [])
    
    for asset in assets:
        balance = asset.get("balance", 0.0)
        current_price = asset.get("current_price", 0.0)
        entry_price = asset.get("entry_price", 0.0)
        
        if balance > 0 and current_price > 0 and entry_price > 0:
            cost_basis = balance * entry_price
            current_value = balance * current_price
            potential_pnl += (current_value - cost_basis)
except Exception as e:
    logger.error(f"Error calculating potential PnL: {e}", exc_info=True)
    potential_pnl = 0.0
```

**Impacto:** 🔴 CRÍTICO - Información crítica para usuarios

---

#### Corrección 2.3: TP/SL Values

**Ubicación:** `backend/app/services/telegram_commands.py:1438-1439`

**Código actual:**
```python
tp_value = 0.0  # TODO: Calculate from TP orders
sl_value = 0.0  # TODO: Calculate from SL orders
```

**Código corregido:**
```python
# Calcular valores de TP/SL desde órdenes abiertas
from app.models.exchange_order import ExchangeOrder, OrderTypeEnum, OrderStatusEnum

tp_value = 0.0
sl_value = 0.0

try:
    # Obtener órdenes TP/SL activas para este símbolo
    tp_orders = db.query(ExchangeOrder).filter(
        ExchangeOrder.symbol == coin,
        ExchangeOrder.order_type == OrderTypeEnum.TAKE_PROFIT,
        ExchangeOrder.status.in_([OrderStatusEnum.NEW, OrderStatusEnum.ACTIVE])
    ).all()
    
    sl_orders = db.query(ExchangeOrder).filter(
        ExchangeOrder.symbol == coin,
        ExchangeOrder.order_type == OrderTypeEnum.STOP_LOSS,
        OrderStatusEnum.status.in_([OrderStatusEnum.NEW, OrderStatusEnum.ACTIVE])
    ).all()
    
    tp_value = sum(
        (order.quantity or 0) * (order.price or 0) 
        for order in tp_orders 
        if order.quantity and order.price
    )
    
    sl_value = sum(
        (order.quantity or 0) * (order.price or 0) 
        for order in sl_orders 
        if order.quantity and order.price
    )
except Exception as e:
    logger.error(f"Error calculating TP/SL values for {coin}: {e}", exc_info=True)
```

**Impacto:** 🟡 ALTO - Información importante para gestión de riesgo

---

### 3. WebSocket Database Updates

#### Corrección 3.1: Balance Updates

**Ubicación:** `backend/app/services/websocket_manager.py:33`

**Código actual:**
```python
def on_balance_update(data):
    logger.info(f"Balance updated via WebSocket")
    # TODO: Update database/cache with new balance
```

**Código corregido:**
```python
def on_balance_update(data):
    logger.info(f"Balance updated via WebSocket: {data}")
    db = SessionLocal()
    try:
        from app.services.exchange_sync import sync_balance_from_data
        sync_balance_from_data(db, data)
        from app.services.portfolio_cache import invalidate_portfolio_cache
        invalidate_portfolio_cache()
        logger.debug(f"Balance updated in database from WebSocket")
    except Exception as e:
        logger.error(f"Error updating balance from WebSocket: {e}", exc_info=True)
        db.rollback()
    finally:
        db.close()
```

**Impacto:** 🟡 ALTO - Sincronización de datos en tiempo real

---

## 📋 Checklist de Implementación

### Fase 1: Excepciones Críticas (Semana 1)
- [ ] Corrección 1.1: Parsing JSON en crypto_com_trade.py
- [ ] Corrección 1.2: Conversión de tipos qty_tick_size
- [ ] Agregar tests para casos de error
- [ ] Verificar que no se rompa funcionalidad existente

### Fase 2: TODOs Críticos (Semanas 2-3)
- [ ] Corrección 2.1: Implementar cálculo de Realized PnL
- [ ] Corrección 2.2: Implementar cálculo de Potential PnL
- [ ] Corrección 2.3: Implementar cálculo de TP/SL values
- [ ] Agregar tests para cálculos de PnL
- [ ] Verificar cálculos con datos reales

### Fase 3: WebSocket Updates (Semana 4)
- [ ] Corrección 3.1: Implementar actualización de balances
- [ ] Implementar actualización de órdenes
- [ ] Implementar actualización de trades
- [ ] Agregar tests para WebSocket updates

---

## 🧪 Testing

### Tests Recomendados

```python
# test_pnl_calculations.py
def test_realized_pnl_calculation():
    """Test que el cálculo de realized PnL es correcto"""
    # Crear órdenes de prueba
    # Verificar cálculo
    pass

def test_potential_pnl_calculation():
    """Test que el cálculo de potential PnL es correcto"""
    pass

def test_tp_sl_values_calculation():
    """Test que los valores de TP/SL se calculan correctamente"""
    pass

# test_exception_handling.py
def test_json_parsing_error_handling():
    """Test que los errores de parsing JSON se manejan correctamente"""
    pass

def test_type_conversion_error_handling():
    """Test que los errores de conversión de tipos se manejan correctamente"""
    pass
```

---

## 📊 Métricas de Éxito

### Antes
- Excepciones genéricas en broker: 65+
- TODOs críticos sin resolver: 4
- Información de PnL: No disponible
- Sincronización WebSocket: No implementada

### Después (objetivo)
- Excepciones genéricas en broker: <10 (solo casos justificados)
- TODOs críticos resueltos: 100%
- Información de PnL: Disponible y precisa
- Sincronización WebSocket: Implementada

---

## ⚠️ Consideraciones Importantes

1. **No cambiar todo de una vez:** Implementar por fases
2. **Agregar tests antes de cambiar:** Asegurar que no se rompa nada
3. **Revisar en staging primero:** Probar antes de producción
4. **Documentar cambios:** Explicar lógica de cálculos
5. **Monitorear en producción:** Verificar que los cálculos sean correctos

---

## 📚 Referencias

- Documento completo: `ANALISIS_EXCEPCIONES_TODOS.md`
- Código fuente: `backend/app/services/brokers/crypto_com_trade.py`
- Código fuente: `backend/app/services/telegram_commands.py`
- Código fuente: `backend/app/services/websocket_manager.py`

---

**Fin del Documento**












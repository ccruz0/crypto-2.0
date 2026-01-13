# Análisis de Excepciones Genéricas y TODOs Críticos

**Fecha:** 2025-01-27  
**Prioridad:** 🔴 CRÍTICA

---

## 📊 Resumen Ejecutivo

- **Excepciones genéricas encontradas:** 789 bloques
- **TODOs encontrados:** 754 items
- **Archivos críticos afectados:** Broker principal, APIs, Servicios de trading

---

## 🔴 EXCEPCIONES GENÉRICAS CRÍTICAS

### 1. Broker Principal - crypto_com_trade.py

**Archivo:** `backend/app/services/brokers/crypto_com_trade.py`  
**Impacto:** 🔴 CRÍTICO - Afecta todas las operaciones de trading

#### Problemas Encontrados:

**1.1. Excepciones genéricas en parsing de respuestas (Líneas 168-179)**
```python
# ❌ PROBLEMA
try:
    return json.loads(body)
except:
    return {}
```

**Riesgo:** 
- Oculta errores de parsing que pueden indicar problemas de API
- Puede retornar datos vacíos sin advertir al usuario
- Dificulta debugging de problemas de comunicación

**Recomendación:**
```python
# ✅ SOLUCIÓN
try:
    return json.loads(body)
except json.JSONDecodeError as e:
    logger.error(f"Failed to parse proxy response as JSON: {e}, body: {body[:200]}")
    return {"error": "Invalid JSON response from proxy"}
except Exception as e:
    logger.error(f"Unexpected error parsing proxy response: {e}", exc_info=True)
    return {"error": f"Error parsing response: {str(e)}"}
```

**1.2. Excepciones genéricas en conversión de tipos (Línea 1237)**
```python
# ❌ PROBLEMA
try:
    qty_tick_size = float(qty_tick_size_str)
except:
    qty_tick_size = 10 ** -quantity_decimals if quantity_decimals else 0.01
```

**Riesgo:**
- Puede usar valores incorrectos sin advertir
- Afecta precisión de órdenes (puede causar errores de trading)

**Recomendación:**
```python
# ✅ SOLUCIÓN
try:
    qty_tick_size = float(qty_tick_size_str)
except (ValueError, TypeError) as e:
    logger.warning(f"Could not parse qty_tick_size '{qty_tick_size_str}': {e}, using fallback")
    qty_tick_size = 10 ** -quantity_decimals if quantity_decimals else 0.01
```

**1.3. Excepciones genéricas en manejo de órdenes (Líneas 955, 1085, 1703, 2008, 2081)**
```python
# ❌ PROBLEMA
except Exception as exc:
    logger.error(f"Trigger orders fetch failed, continuing with standard orders only: {exc}")
```

**Riesgo:**
- Puede ocultar errores críticos de API
- Puede causar pérdida de órdenes importantes (SL/TP)

**Recomendación:**
```python
# ✅ SOLUCIÓN
except requests.RequestException as e:
    logger.error(f"Network error fetching trigger orders: {e}")
    # Retry logic or failover
except (KeyError, ValueError) as e:
    logger.error(f"Data format error in trigger orders response: {e}")
    # Handle specific data issues
except Exception as exc:
    logger.error(f"Unexpected error fetching trigger orders: {exc}", exc_info=True)
    # Re-raise if critical, or handle gracefully
```

---

### 2. APIs - Múltiples archivos

**Archivos afectados:** 25 archivos en `backend/app/api/`

**Problema común:**
- Uso de `except Exception` genérico sin especificar tipos
- Puede ocultar errores de validación, autenticación, o base de datos

**Recomendación general:**
```python
# ✅ PATRÓN RECOMENDADO
from fastapi import HTTPException
from sqlalchemy.exc import SQLAlchemyError

try:
    # Operación
    pass
except ValueError as e:
    raise HTTPException(status_code=400, detail=f"Invalid input: {e}")
except SQLAlchemyError as e:
    logger.error(f"Database error: {e}", exc_info=True)
    raise HTTPException(status_code=500, detail="Database error")
except Exception as e:
    logger.error(f"Unexpected error: {e}", exc_info=True)
    raise HTTPException(status_code=500, detail="Internal server error")
```

---

## 📝 TODOs CRÍTICOS PRIORIZADOS

### Prioridad 1: 🔴 CRÍTICO - Funcionalidad de Trading

#### 1. Cálculo de PnL en Telegram Commands

**Archivo:** `backend/app/services/telegram_commands.py`  
**Líneas:** 1382-1383, 1438-1439

**Problema:**
```python
realized_pnl = 0.0  # TODO: Calculate from executed orders
potential_pnl = 0.0  # TODO: Calculate from open positions (unrealized)
tp_value = 0.0  # TODO: Calculate from TP orders
sl_value = 0.0  # TODO: Calculate from SL orders
```

**Impacto:**
- Los usuarios no pueden ver PnL real en Telegram
- Información crítica de trading no disponible
- Afecta decisiones de trading

**Recomendación:**
```python
# Calcular realized_pnl desde order_history
from app.models.order_history import OrderHistory
from app.services.order_position_service import calculate_realized_pnl

realized_pnl = calculate_realized_pnl(db)

# Calcular potential_pnl desde posiciones abiertas
from app.services.portfolio_cache import get_portfolio_summary
portfolio = get_portfolio_summary(db)
potential_pnl = sum(asset.get("unrealized_pnl", 0) for asset in portfolio.get("assets", []))

# Calcular TP/SL values desde órdenes abiertas
from app.models.exchange_order import ExchangeOrder, OrderTypeEnum
tp_orders = db.query(ExchangeOrder).filter(
    ExchangeOrder.order_type == OrderTypeEnum.TAKE_PROFIT,
    ExchangeOrder.status.in_([OrderStatusEnum.NEW, OrderStatusEnum.ACTIVE])
).all()
tp_value = sum(order.quantity * order.price for order in tp_orders if order.quantity and order.price)
```

**Esfuerzo estimado:** 4-6 horas

---

#### 2. Actualización de Base de Datos desde WebSocket

**Archivo:** `backend/app/services/websocket_manager.py`  
**Líneas:** 33, 38, 43

**Problema:**
```python
def on_balance_update(data):
    logger.info(f"Balance updated via WebSocket")
    # TODO: Update database/cache with new balance

def on_order_update(data):
    logger.info(f"Order updated via WebSocket")
    # TODO: Update database/cache with new order status

def on_trade_update(data):
    logger.info(f"Trade executed via WebSocket")
    # TODO: Update database/cache with new trade
```

**Impacto:**
- Los datos de WebSocket no se persisten
- Puede causar inconsistencias entre estado real y base de datos
- Afecta precisión de reportes y dashboard

**Recomendación:**
```python
from app.database import SessionLocal
from app.models.exchange_order import ExchangeOrder
from app.services.portfolio_cache import invalidate_portfolio_cache

def on_balance_update(data):
    logger.info(f"Balance updated via WebSocket: {data}")
    db = SessionLocal()
    try:
        # Actualizar balance en base de datos
        # Usar exchange_sync service o crear método específico
        from app.services.exchange_sync import update_balance_from_websocket
        update_balance_from_websocket(db, data)
        invalidate_portfolio_cache()
    except Exception as e:
        logger.error(f"Error updating balance from WebSocket: {e}", exc_info=True)
    finally:
        db.close()

def on_order_update(data):
    logger.info(f"Order updated via WebSocket: {data}")
    db = SessionLocal()
    try:
        # Actualizar estado de orden
        order_id = data.get("order_id") or data.get("id")
        if order_id:
            order = db.query(ExchangeOrder).filter(ExchangeOrder.order_id == order_id).first()
            if order:
                order.status = data.get("status")
                order.quantity_filled = data.get("quantity_filled", 0)
                db.commit()
    except Exception as e:
        logger.error(f"Error updating order from WebSocket: {e}", exc_info=True)
        db.rollback()
    finally:
        db.close()
```

**Esfuerzo estimado:** 6-8 horas

---

### Prioridad 2: 🟡 ALTA - Performance y Optimización

#### 3. Optimización de Queries en Dashboard

**Archivo:** `backend/app/api/routes_dashboard.py.backup2`  
**Líneas:** 345, 375, 468, 474

**Problema:**
```python
# TODO: Fix database connection/query performance issues
# TODO: Fix get_portfolio_summary performance or move to async/background task
# TODO: Optimize TradeSignal queries or move to separate endpoint
# TODO: Optimize ExchangeOrder query or move to separate endpoint
```

**Impacto:**
- Timeouts en dashboard
- Mala experiencia de usuario
- Puede causar errores 502

**Recomendación:**
- Implementar caching agresivo
- Mover queries pesadas a endpoints separados
- Usar background tasks para actualización de datos
- Optimizar queries con índices apropiados

**Esfuerzo estimado:** 8-12 horas

---

## 📋 Plan de Acción Recomendado

### Fase 1: Excepciones Críticas (1-2 semanas)

**Semana 1:**
- [ ] Corregir excepciones en `crypto_com_trade.py` (parsing, conversiones)
- [ ] Agregar tipos específicos de excepciones
- [ ] Mejorar logging de errores

**Semana 2:**
- [ ] Revisar y corregir excepciones en APIs principales
- [ ] Implementar manejo de errores consistente
- [ ] Agregar tests para casos de error

### Fase 2: TODOs Críticos (2-3 semanas)

**Semana 3:**
- [ ] Implementar cálculo de PnL en Telegram
- [ ] Agregar tests para cálculos de PnL

**Semana 4:**
- [ ] Implementar actualización de DB desde WebSocket
- [ ] Agregar sincronización de balances y órdenes

**Semana 5:**
- [ ] Optimizar queries del dashboard
- [ ] Implementar caching donde sea apropiado

---

## 🔧 Scripts de Análisis

### Contar excepciones genéricas por archivo
```bash
cd backend/app
for file in $(find . -name "*.py"); do
    count=$(grep -c "except\s*:\|except\s+Exception" "$file" 2>/dev/null || echo 0)
    if [ "$count" -gt 0 ]; then
        echo "$count: $file"
    fi
done | sort -rn | head -20
```

### Buscar TODOs críticos
```bash
grep -rn "TODO.*[Pp]nl\|TODO.*[Pp]rofit\|TODO.*[Tt]rading\|TODO.*[Oo]rder" backend/app --include="*.py"
```

---

## 📊 Métricas de Mejora

### Antes
- Excepciones genéricas: 789
- TODOs críticos sin resolver: 4+
- Riesgo de errores ocultos: ALTO

### Después (objetivo)
- Excepciones genéricas: <100 (solo en casos justificados)
- TODOs críticos resueltos: 100%
- Riesgo de errores ocultos: BAJO

---

## ⚠️ Notas Importantes

1. **No cambiar todo de una vez:** Priorizar por impacto
2. **Agregar tests:** Cada corrección debe tener tests
3. **Documentar cambios:** Explicar por qué se cambió
4. **Revisar en producción:** Verificar que no se rompa nada

---

## 📚 Referencias

- Python Exception Handling Best Practices: https://docs.python.org/3/tutorial/errors.html
- FastAPI Error Handling: https://fastapi.tiangolo.com/tutorial/handling-errors/
- SQLAlchemy Exception Handling: https://docs.sqlalchemy.org/en/20/core/exceptions.html

---

**Fin del Análisis**

















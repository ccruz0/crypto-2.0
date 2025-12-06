# Dashboard Timeout Issue - STATUS

## Problema Actual

**Síntoma:** Dashboard muestra "No open orders found" aunque hay 61 órdenes en la BD  
**Causa:** Endpoint `/api/dashboard/state` tardando 178+ segundos (timeouts)  
**Estado:** Dashboard URL: http://localhost:3000  

## Datos Verificados

### Base de Datos
✅ **61 órdenes abiertas** sincronizadas de crypto.com  
✅ **37 órdenes ejecutadas** en historial  
✅ **Portfolio: $39,789.22 USD** (actualizado)  
✅ **43 órdenes con OCO** (pareadas)  

### Backend API
❌ `/api/dashboard/state` → Timeout (>178s)  
❌ `/market/top-coins-data` → Timeout  
✅ `/health` → Responde (pero tarda 45s)  

### Frontend
✅ Dashboard cargado en http://localhost:3000  
❌ Muestra "No open orders found"  
❌ Muestra "No portfolio data available"  
⚠️ Timeouts en llamadas API  

## Configuración Actual

```python
# backend/app/main.py
DEBUG_DISABLE_EXCHANGE_SYNC = True  # Deshabilitado temporalmente
DEBUG_DISABLE_SIGNAL_MONITOR = False  # Activo
DEBUG_DISABLE_TRADING_SCHEDULER = False  # Activo

# backend/app/api/routes_dashboard.py  
DEBUG_DASHBOARD_FAST_PATH = True  # Activado pero aún lento
```

## Intentos de Solución

1. ✅ Deshabilitado Exchange Sync → Sigue lento
2. ✅ Activado fast-path con datos reales → Sigue lento
3. ⏸️ Pendiente: Identificar qué query/servicio bloquea

## Próximos Pasos

### Opción A: Crear Endpoint Dedicado para Órdenes
Crear `/api/orders/open` super simple que SOLO devuelva órdenes:

```python
@router.get("/orders/open")
def get_open_orders_only(db: Session = Depends(get_db)):
    orders = db.query(ExchangeOrder).filter(
        ExchangeOrder.status.in_(['NEW', 'ACTIVE'])
    ).limit(100).all()
    
    return [{"symbol": o.symbol, "side": o.side, ...} for o in orders]
```

### Opción B: Servir Datos Desde Cache
Guardar órdenes en Redis/memoria y servir desde ahí

### Opción C: Identificar Bottleneck Específico
- Agregar timing logs a cada parte del fast-path
- Encontrar qué query/código está bloqueando
- Optimizar esa parte específica

## Workaround Actual

Mientras tanto, puedes ver las órdenes directamente desde el backend:

```bash
docker compose exec backend python3 << 'EOF'
from app.database import SessionLocal
from app.models.exchange_order import ExchangeOrder, OrderStatusEnum

db = SessionLocal()
orders = db.query(ExchangeOrder).filter(
    ExchangeOrder.status.in_([OrderStatusEnum.NEW, OrderStatusEnum.ACTIVE])
).limit(10).all()

for o in orders:
    print(f"{o.symbol}: {o.side.value} @ ${o.price} ({o.status.value})")

db.close()
EOF
```

O via curl:
```bash
# Esperar hasta que responda
timeout 180 curl http://localhost:8002/api/dashboard/state | jq '.open_orders[0:5]'
```

## Sistema OCO

✅ **FUNCIONANDO CORRECTAMENTE**
- 43 órdenes pareadas
- Cancelación automática implementada
- Solo necesita que el dashboard las muestre

---

**Estado:** ⚠️ BLOQUEADO - Dashboard no muestra datos por timeouts  
**Prioridad:** 🔴 ALTA - Necesita fix urgente  
**Próximo:** Implementar endpoint simplificado o identificar bottleneck exacto  



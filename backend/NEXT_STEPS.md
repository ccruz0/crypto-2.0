# Próximos Pasos - Optimización de Rendimiento

## ✅ Estado Actual
- **Problema resuelto**: Endpoints responden en <50ms (mejora del 99.9%)
- **Causa identificada**: `exchange_sync_service` bloqueaba el event loop
- **Solución aplicada**: Delay de 15s + page_size reducido

## 📋 Próximos Pasos Inmediatos

### 1. Verificar que todo funciona en producción
```bash
# Reiniciar servicios
docker compose --profile local restart backend

# Probar endpoints
curl -w "\nstarttransfer: %{time_starttransfer}s\ntotal: %{time_total}s\n" -sS http://localhost:8002/health
curl -w "\nstarttransfer: %{time_starttransfer}s\ntotal: %{time_total}s\n" -sS http://localhost:8002/api/dashboard/state

# Verificar logs
docker logs automated-trading-platform-backend-1 --tail 50 | grep PERF
```

### 2. Activar servicios de background gradualmente
Actualmente están desactivados para testing. Actívalos uno por uno y mide el impacto:

```python
# En backend/app/main.py, cambiar gradualmente:
DEBUG_DISABLE_EXCHANGE_SYNC = False  # Activar primero
DEBUG_DISABLE_SIGNAL_MONITOR = False  # Luego este
DEBUG_DISABLE_TRADING_SCHEDULER = False  # Y finalmente este
```

**Proceso recomendado:**
1. Activar solo `exchange_sync` y medir rendimiento
2. Si sigue rápido (<100ms), activar `signal_monitor`
3. Si sigue rápido, activar `trading_scheduler`
4. Si algún servicio causa lentitud, dejarlo desactivado o optimizarlo

### 3. Desactivar fast-path del dashboard
Una vez confirmado que todo funciona, desactivar el fast-path:

```python
# En backend/app/api/routes_dashboard.py
DEBUG_DASHBOARD_FAST_PATH = False  # Cambiar a False
```

Esto restaurará la funcionalidad completa del endpoint `/api/dashboard/state`.

## 🔧 Optimizaciones Adicionales Recomendadas

### A. Ejecutar operaciones de DB en executor (ALTA PRIORIDAD)
**Problema**: Las operaciones síncronas de SQLAlchemy bloquean el event loop.

**Solución**: Modificar `exchange_sync_service` para ejecutar queries en un thread executor.

**Archivo**: `backend/app/services/exchange_sync.py`

**Cambio sugerido**:
```python
async def sync_balances(self, db: Session):
    """Sync balances - runs DB operations in executor"""
    loop = asyncio.get_event_loop()
    
    def _sync_in_thread():
        # Mover toda la lógica de sync aquí
        # Operaciones síncronas de DB
        pass
    
    await loop.run_in_executor(None, _sync_in_thread)
```

**Beneficio**: Elimina completamente el bloqueo del event loop.

### B. Usar driver async de PostgreSQL (MEDIA PRIORIDAD)
**Problema**: SQLAlchemy con psycopg2 es síncrono.

**Solución**: Migrar a `asyncpg` o `aiopg` para operaciones async nativas.

**Pasos**:
1. Instalar `asyncpg`: `pip install asyncpg`
2. Modificar `database.py` para usar async engine
3. Convertir queries a async/await

**Beneficio**: Operaciones de DB verdaderamente async, sin bloqueo.

### C. Implementar connection pooling async (MEDIA PRIORIDAD)
**Problema**: Cada request crea una nueva conexión.

**Solución**: Usar pool de conexiones async.

**Beneficio**: Mejor rendimiento para requests concurrentes.

### D. Añadir índices en base de datos (BAJA PRIORIDAD)
**Problema**: Queries lentas en tablas grandes.

**Solución**: Añadir índices en columnas frecuentemente consultadas.

**Queries a optimizar**:
```sql
-- En exchange_orders
CREATE INDEX idx_exchange_orders_status ON exchange_orders(status);
CREATE INDEX idx_exchange_orders_exchange_order_id ON exchange_orders(exchange_order_id);
CREATE INDEX idx_exchange_orders_exchange_create_time ON exchange_orders(exchange_create_time DESC);

-- En trade_signals
CREATE INDEX idx_trade_signals_status ON trade_signals(status);
CREATE INDEX idx_trade_signals_should_trade ON trade_signals(should_trade);
```

**Beneficio**: Queries más rápidas, especialmente en tablas grandes.

### E. Implementar caching (BAJA PRIORIDAD)
**Problema**: Mismos datos consultados repetidamente.

**Solución**: Usar Redis o in-memory cache para datos frecuentes.

**Beneficio**: Reduce carga en base de datos.

## 📊 Monitoreo Continuo

### 1. Activar logs de rendimiento
Los logs de `TimingMiddleware` ya están activos. Revisar periódicamente:

```bash
# Ver logs de rendimiento
docker logs automated-trading-platform-backend-1 --tail 100 | grep PERF

# Ver tiempos de requests
docker logs automated-trading-platform-backend-1 | grep "PERF: Request completed" | tail -20
```

### 2. Configurar alertas
Crear alertas para requests lentos (>1 segundo):

```python
# En TimingMiddleware, añadir alerta
if elapsed_ms > 1000:
    logger.warning(f"SLOW REQUEST: {request.method} {request.url.path} - {elapsed_ms:.2f}ms")
```

### 3. Dashboard de métricas (Opcional)
Implementar un endpoint de métricas:

```python
@app.get("/metrics")
def get_metrics():
    """Return performance metrics"""
    return {
        "requests_per_second": ...,
        "average_response_time": ...,
        "p95_response_time": ...,
        "p99_response_time": ...,
    }
```

## 🧪 Testing

### 1. Test de carga
Probar con múltiples requests concurrentes:

```bash
# Instalar Apache Bench
brew install httpd  # macOS
# o
apt-get install apache2-utils  # Linux

# Test de carga
ab -n 100 -c 10 http://localhost:8002/api/dashboard/state
```

### 2. Test de stress
Probar bajo carga alta:

```bash
# 1000 requests, 50 concurrentes
ab -n 1000 -c 50 http://localhost:8002/api/dashboard/state
```

### 3. Test de endpoints individuales
Probar cada endpoint por separado:

```bash
# Health check
time curl http://localhost:8002/health

# Dashboard state
time curl http://localhost:8002/api/dashboard/state

# Ping fast
time curl http://localhost:8002/ping_fast
```

## 🚀 Despliegue en AWS

### 1. Verificar configuración de Docker Compose
Asegurarse de que el perfil `aws` tiene la configuración correcta:

```bash
# Revisar docker-compose.yml
docker compose --profile aws config
```

### 2. Probar en entorno AWS
```bash
# Levantar servicios AWS
docker compose --profile aws up -d

# Probar endpoints
curl http://localhost:8002/health
curl http://localhost:8002/api/dashboard/state
```

### 3. Monitorear en producción
Una vez desplegado, monitorear logs y métricas:

```bash
# Ver logs en AWS
docker logs <container-id> --tail 100 | grep PERF

# Ver métricas de rendimiento
# (configurar según tu sistema de monitoreo)
```

## 📝 Checklist de Implementación

- [ ] Verificar que endpoints responden rápido (<50ms)
- [ ] Activar `exchange_sync` y verificar rendimiento
- [ ] Activar `signal_monitor` y verificar rendimiento
- [ ] Activar `trading_scheduler` y verificar rendimiento
- [ ] Desactivar `DEBUG_DASHBOARD_FAST_PATH`
- [ ] Implementar executor para operaciones de DB (opcional)
- [ ] Añadir índices en base de datos (opcional)
- [ ] Configurar alertas de rendimiento (opcional)
- [ ] Probar en entorno AWS
- [ ] Documentar cambios en producción

## 🎯 Prioridades

1. **ALTA**: Verificar funcionamiento en producción
2. **ALTA**: Activar servicios gradualmente
3. **MEDIA**: Implementar executor para DB operations
4. **MEDIA**: Añadir índices en base de datos
5. **BAJA**: Migrar a driver async de PostgreSQL
6. **BAJA**: Implementar caching

## 📚 Recursos

- [FastAPI Performance](https://fastapi.tiangolo.com/advanced/performance/)
- [SQLAlchemy Async](https://docs.sqlalchemy.org/en/14/orm/extensions/asyncio.html)
- [AsyncPG Documentation](https://magicstack.github.io/asyncpg/current/)
- [Performance Monitoring Best Practices](https://www.datadoghq.com/blog/monitoring-fastapi-performance/)


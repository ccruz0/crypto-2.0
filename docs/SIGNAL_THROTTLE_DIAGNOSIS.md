# Signal Throttle - Diagnóstico y Solución

**Fecha:** 2025-12-09  
**Problema:** Signal throttle no envía señales desde hace días

---

## Problema Identificado

El dashboard muestra que los últimos eventos de signal throttle ocurrieron hace 5-8 días. Esto indica que:

1. **El signal monitor NO está corriendo** (verificado con script de diagnóstico)
2. Los eventos en la base de datos están desactualizados
3. No hay nuevos registros de throttle desde hace varios días

---

## Diagnóstico Realizado

### 1. Estado del Signal Monitor
- **is_running:** `False`
- **Status file:** No encontrado (`/tmp/signal_monitor_status.json`)
- **Conclusión:** El servicio no está activo

### 2. Posibles Causas

#### A. Signal Monitor Deshabilitado
- Verificar que `DEBUG_DISABLE_SIGNAL_MONITOR = False` en `backend/app/main.py`
- Si está en `True`, el servicio no se iniciará

#### B. Servicio No Iniciado
- El servicio debe iniciarse automáticamente al arrancar el backend
- Verificar logs del backend al iniciar
- Buscar mensajes: "Starting Signal monitor service..." o "Signal monitor service start() scheduled"

#### C. Servicio Crasheado
- El servicio puede haber iniciado pero luego crasheado
- Revisar logs del backend para errores
- Verificar si hay excepciones no capturadas

---

## Solución

### Paso 1: Verificar Configuración

Verificar que el signal monitor esté habilitado:

```python
# backend/app/main.py línea 47
DEBUG_DISABLE_SIGNAL_MONITOR = False  # Debe ser False
```

### Paso 2: Verificar Inicio del Servicio

El servicio debe iniciarse en `backend/app/main.py` en la función `startup_event`:

```python
if not DEBUG_DISABLE_SIGNAL_MONITOR:
    try:
        logger.info("🔧 Starting Signal monitor service...")
        from app.services.signal_monitor import signal_monitor_service
        loop = asyncio.get_running_loop()
        signal_monitor_service.start_background(loop)
        logger.info("✅ Signal monitor service start() scheduled")
    except Exception as e:
        logger.error(f"❌ Failed to start signal monitor: {e}", exc_info=True)
```

### Paso 3: Reiniciar el Backend

Si el servicio está en AWS:

```bash
# Conectar a AWS
ssh hilovivo-aws

# Reiniciar el contenedor del backend
cd /home/ubuntu/crypto-2.0
docker compose restart backend-aws
```

O si está corriendo localmente:

```bash
# Detener y reiniciar
docker compose down
docker compose up -d backend
```

### Paso 4: Verificar que el Servicio Está Corriendo

Después de reiniciar, verificar logs:

```bash
# En AWS
docker compose logs -f backend-aws | grep -i "signal monitor"

# Deberías ver:
# - "🔧 Starting Signal monitor service..."
# - "✅ Signal monitor service start() scheduled"
# - "SignalMonitorService.start() called, entering main loop"
# - "SignalMonitorService cycle #1 started"
```

### Paso 5: Verificar Watchlist Items

Asegurarse de que hay items en la watchlist con `alert_enabled=True`:

```sql
SELECT symbol, alert_enabled, buy_alert_enabled, sell_alert_enabled 
FROM watchlist_items 
WHERE alert_enabled = true 
AND is_deleted = false;
```

---

## Cómo Funciona el Signal Throttle

### Flujo de Procesamiento

1. **Signal Monitor Service** corre cada 30 segundos (configurable)
2. Para cada item con `alert_enabled=True`:
   - Obtiene precio e indicadores técnicos
   - Calcula señales (BUY/SELL) usando `calculate_trading_signals()`
   - Verifica throttle usando `should_emit_signal()`
   - Si pasa throttle: envía alerta y registra evento con `record_signal_event()`
   - Si no pasa throttle: registra mensaje bloqueado pero NO registra evento

### Registro de Eventos

Los eventos se registran en la tabla `signal_throttle_state` SOLO cuando:
- Una señal pasa el throttle
- Se envía una alerta exitosamente
- Se llama a `record_signal_event()`

**IMPORTANTE:** Si todas las señales están siendo bloqueadas por throttle, NO se registrarán eventos nuevos.

---

## Verificación Post-Solución

### 1. Verificar Estado del Servicio

```bash
# Script de diagnóstico
python3 scripts/diagnose_signal_throttle.py
```

Debería mostrar:
- ✅ `is_running: True`
- ✅ Watchlist items con `alert_enabled=True`
- ✅ Eventos recientes en la base de datos

### 2. Verificar Logs

Buscar en logs del backend:

```bash
# Señales detectadas
grep "BUY signal detected" logs/*.log

# Alertas enviadas
grep "BUY alert sent" logs/*.log

# Señales bloqueadas por throttle
grep "BLOQUEADO.*THROTTLED" logs/*.log
```

### 3. Verificar Dashboard

En el dashboard (`dashboard.hilovivo.com`):
- Ir a la sección "Signal Throttle"
- Verificar que aparezcan eventos recientes (últimas horas, no días)
- Si aparecen eventos, el servicio está funcionando

---

## Troubleshooting Adicional

### Si el Servicio No Inicia

1. **Verificar dependencias:**
   ```bash
   # Verificar que la base de datos esté accesible
   docker compose exec backend-aws python -c "from app.database import SessionLocal; db = SessionLocal(); db.close()"
   ```

2. **Verificar permisos:**
   ```bash
   # Verificar que el archivo de status pueda escribirse
   docker compose exec backend-aws touch /tmp/signal_monitor_status.json
   ```

3. **Revisar logs completos:**
   ```bash
   docker compose logs backend-aws | tail -100
   ```

### Si el Servicio Inicia pero No Detecta Señales

1. **Verificar watchlist items:**
   - Asegurarse de que hay items con `alert_enabled=True`
   - Verificar que `buy_alert_enabled=True` o `sell_alert_enabled=True` según corresponda

2. **Verificar condiciones de señal:**
   - Revisar logs para ver si las señales se están detectando pero bloqueando
   - Verificar configuración de throttle (min_price_change_pct, min_interval_minutes)

3. **Verificar datos de mercado:**
   - Asegurarse de que hay datos de precio e indicadores disponibles
   - Verificar que `MarketData` o `MarketPrice` tienen datos actualizados

---

## Archivos Relacionados

- `backend/app/services/signal_monitor.py` - Servicio principal
- `backend/app/services/signal_throttle.py` - Lógica de throttle
- `backend/app/main.py` - Inicio del servicio
- `backend/app/api/routes_monitoring.py` - Endpoint `/monitoring/signal-throttle`
- `scripts/diagnose_signal_throttle.py` - Script de diagnóstico

---

## Próximos Pasos

1. ✅ Verificar configuración (`DEBUG_DISABLE_SIGNAL_MONITOR`)
2. ✅ Reiniciar backend
3. ✅ Verificar logs para confirmar inicio del servicio
4. ✅ Esperar 1-2 ciclos (30-60 segundos) y verificar dashboard
5. ✅ Si sigue sin funcionar, revisar logs detallados

---

**Última Actualización:** 2025-12-09

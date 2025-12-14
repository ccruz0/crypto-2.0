# Diagnóstico: Por qué no recibes alertas desde ayer

## 🔍 Problema Identificado

### 1. **Scheduler NO está corriendo**
- El scheduler es responsable de ejecutar workflows como:
  - `SL/TP Check` (diario a las 8:00 AM)
  - `Daily Summary` (diario a las 8:00 AM)
  - `Sell Orders Report` (diario a las 7:00 AM)
  - `Watchlist Consistency Check` (diario a las 3:00 AM)

**Estado actual**: `Scheduler running: False`

### 2. **Workflows muestran status "unknown"**
- Los workflows muestran "unknown" porque no se han ejecutado desde que se reinició el servicio
- Esto es normal si el scheduler no está corriendo

### 3. **Signal Throttle bloqueando alertas**
- El sistema de throttling está funcionando correctamente
- Las señales están siendo bloqueadas porque:
  - No ha pasado suficiente tiempo desde la última señal (cooldown)
  - El precio no ha cambiado lo suficiente (min_price_change_pct)
- Esto es **comportamiento esperado** del sistema de throttling

## ✅ Solución Aplicada

### Iniciar el Scheduler

El scheduler debe iniciarse automáticamente al arrancar el servicio, pero parece que no se inició después del reinicio.

**Solución manual:**
```bash
curl -X POST http://localhost:8002/api/control/start-scheduler
```

**O verificar que se inicie automáticamente:**
El scheduler debería iniciarse automáticamente en `backend/app/main.py` cuando el servicio arranca.

## 📊 Estado Esperado Después del Fix

1. **Scheduler corriendo**: `Scheduler running: True`
2. **Workflows ejecutándose** según su horario:
   - `SL/TP Check`: Diario a las 8:00 AM
   - `Daily Summary`: Diario a las 8:00 AM
   - `Sell Orders Report`: Diario a las 7:00 AM
   - `Watchlist Consistency Check`: Diario a las 3:00 AM
3. **Alertas funcionando** cuando:
   - Las condiciones de trading se cumplan
   - El throttling permita emitir la señal (cooldown y cambio de precio)

## 🔍 Verificación

### Verificar que el scheduler está corriendo:
```bash
docker compose --profile aws exec backend-aws python3 -c "from app.services.scheduler import trading_scheduler; print(f'Scheduler running: {trading_scheduler.running}')"
```

### Ver logs del scheduler:
```bash
docker compose --profile aws logs backend-aws | grep -i "scheduler\|workflow"
```

### Verificar ejecuciones de workflows:
```bash
docker compose --profile aws logs backend-aws | grep -i "workflow.*execution"
```

## ⚠️ Nota sobre Alertas

Las alertas pueden no aparecer si:
1. **Throttling activo**: El sistema bloquea señales si:
   - No ha pasado el tiempo mínimo entre señales (cooldown)
   - El precio no ha cambiado lo suficiente (min_price_change_pct)
2. **Condiciones de trading no se cumplen**: RSI, MAs, etc. no cumplen los criterios
3. **Alertas deshabilitadas**: `alert_enabled=False` en la watchlist

Esto es **comportamiento esperado** del sistema para evitar spam de alertas.


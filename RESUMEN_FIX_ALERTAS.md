# Resumen del Fix: Alertas de Compra no Saltaban

## Problema Identificado

Cuando cambiabas `trade_enabled` a `YES` para DOT o BTC, no saltaba la alerta de compra aunque el dashboard mostraba BUY con INDEX:100%.

## Causas Encontradas

### 1. **Falta de `alert_enabled` (Master Switch)**
- Al cambiar `trade_enabled` a `YES`, se habilitaban `buy_alert_enabled` y `sell_alert_enabled`
- Pero NO se habilitaba `alert_enabled` (master switch)
- El sistema requiere AMBOS: `alert_enabled=True` Y `buy_alert_enabled=True` para enviar alertas

### 2. **Discrepancia entre Dashboard y Signal Monitor**
- **Dashboard**: Usa `strategy.decision` del endpoint `/api/signals` → muestra BUY
- **Signal Monitor**: Usaba solo `buy_signal` de `calculate_trading_signals` → no detectaba BUY
- Había una inconsistencia entre ambos sistemas

## Soluciones Implementadas

### Fix 1: Auto-habilitar `alert_enabled` cuando `trade_enabled` cambia a YES
**Archivo**: `backend/app/api/routes_dashboard.py` (líneas 1620-1633)

**Cambio**:
```python
# Cuando trade_enabled se cambia a YES, también se habilita automáticamente:
- alert_enabled (master switch) ← NUEVO
- buy_alert_enabled
- sell_alert_enabled
```

### Fix 2: Signal Monitor usa `strategy.decision` como fuente primaria
**Archivo**: `backend/app/services/signal_monitor.py` (líneas 1049-1061)

**Cambio**:
```python
# Ahora signal_monitor usa strategy.decision (igual que el dashboard):
1. Si hay señales manuales → usa manuales
2. Si hay strategy.decision → usa esa decisión (PRIORIDAD) ← NUEVO
3. Si no → usa buy_signal/sell_signal como fallback
```

## Archivos Modificados

1. ✅ `backend/app/api/routes_dashboard.py` - Auto-habilita `alert_enabled`
2. ✅ `backend/app/services/signal_monitor.py` - Usa `strategy.decision` como fuente primaria

## Pasos para Aplicar el Fix en AWS

### Opción 1: Sincronizar y Reiniciar (Recomendado)
```bash
# Desde tu máquina local:
cd ~/automated-trading-platform

# Sincronizar archivos modificados
rsync -avz -e "ssh -i ~/.ssh/id_rsa" \
  backend/app/api/routes_dashboard.py \
  backend/app/services/signal_monitor.py \
  ubuntu@54.254.150.31:~/automated-trading-platform/backend/app/

# Conectarte a AWS y reiniciar
ssh ubuntu@54.254.150.31
cd ~/automated-trading-platform
docker compose --profile aws restart backend
```

### Opción 2: Usar Script de Sincronización
```bash
# Si tienes acceso SSH configurado:
./sync_fix_and_restart.sh
```

### Opción 3: Reinicio Manual en AWS
```bash
# Conectarte vía SSH
ssh ubuntu@54.254.150.31

# Ir al directorio del proyecto
cd ~/automated-trading-platform

# Copiar archivos al contenedor (si ya están sincronizados)
docker cp backend/app/api/routes_dashboard.py $(docker compose --profile aws ps -q backend):/app/app/api/routes_dashboard.py
docker cp backend/app/services/signal_monitor.py $(docker compose --profile aws ps -q backend):/app/app/services/signal_monitor.py

# Reiniciar backend
docker compose --profile aws restart backend

# Verificar logs
docker compose --profile aws logs --tail=50 backend | grep -E "(signal_monitor|strategy.decision)"
```

## Verificación Post-Fix

### 1. Verificar que los cambios están aplicados
```bash
# En el servidor AWS:
docker compose --profile aws exec backend grep -A 5 "strategy.decision" /app/app/services/signal_monitor.py
```

### 2. Verificar en el Dashboard
- Abre `https://dashboard.hilovivo.com`
- Busca BTC o DOT en la watchlist
- Verifica que muestra BUY con INDEX:100%
- Verifica que `alert_enabled`, `buy_alert_enabled` y `trade_enabled` están en YES

### 3. Probar el Fix
1. Cambia `trade_enabled` de NO → YES para un símbolo
2. Verifica que automáticamente se habilitan:
   - `alert_enabled` ✅
   - `buy_alert_enabled` ✅
   - `sell_alert_enabled` ✅
3. Si hay una señal BUY válida, espera al próximo ciclo de `signal_monitor` (30 segundos)
4. La alerta debería saltar automáticamente

## Estado Actual

- ✅ **Backend responde**: `https://dashboard.hilovivo.com/api/health` → OK
- ✅ **Flags de BTC**: `alert_enabled=YES`, `buy_alert_enabled=YES`, `trade_enabled=YES`
- ⚠️  **Señal actual**: `strategy.decision=WAIT` (no hay señal BUY en este momento)
- ✅ **Fix implementado**: Código actualizado localmente, necesita sincronizarse a AWS

## Notas Importantes

1. **El fix requiere reinicio del backend** para aplicarse
2. **Los cambios están en tu máquina local**, necesitas sincronizarlos a AWS
3. **Después del reinicio**, cuando el dashboard muestre BUY, `signal_monitor` también lo detectará
4. **El próximo ciclo de `signal_monitor`** (cada 30 segundos) evaluará las señales con la nueva lógica

## Próximos Pasos

1. ✅ Código corregido localmente
2. ⏳ Sincronizar archivos a AWS (requiere acceso SSH)
3. ⏳ Reiniciar backend en AWS
4. ⏳ Verificar en dashboard que funciona correctamente
5. ⏳ Probar cambiando `trade_enabled` a YES y verificar que salta la alerta










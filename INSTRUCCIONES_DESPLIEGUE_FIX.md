# Instrucciones para Desplegar el Fix de Alertas

## ✅ Cambios Realizados (Localmente)

### Archivos Modificados:
1. `backend/app/api/routes_dashboard.py` - Auto-habilita `alert_enabled` cuando `trade_enabled` cambia a YES
2. `backend/app/services/signal_monitor.py` - Usa `strategy.decision` como fuente primaria (igual que dashboard)

## 🚀 Pasos para Desplegar en AWS

### Opción 1: Sincronización Rápida (Solo archivos modificados)

```bash
cd ~/automated-trading-platform

# Sincronizar archivos
rsync -avz -e "ssh -i ~/.ssh/id_rsa -o StrictHostKeyChecking=no" \
  backend/app/api/routes_dashboard.py \
  backend/app/services/signal_monitor.py \
  ubuntu@54.254.150.31:~/automated-trading-platform/backend/app/

# Conectarse y reiniciar
ssh -i ~/.ssh/id_rsa ubuntu@54.254.150.31 << 'EOF'
cd ~/automated-trading-platform

# Copiar al contenedor
CONTAINER=$(docker compose --profile aws ps -q backend)
docker cp backend/app/api/routes_dashboard.py $CONTAINER:/app/app/api/routes_dashboard.py
docker cp backend/app/services/signal_monitor.py $CONTAINER:/app/app/services/signal_monitor.py

# Reiniciar
docker compose --profile aws restart backend

# Verificar
sleep 5
docker compose --profile aws logs --tail=30 backend | grep -E "(signal_monitor|strategy.decision)"
EOF
```

### Opción 2: Usar Script de Sincronización Completo

```bash
# Si tienes acceso SSH configurado, puedes usar:
./sync_to_aws.sh

# Luego reiniciar manualmente:
ssh ubuntu@54.254.150.31
cd ~/automated-trading-platform
docker compose --profile aws restart backend
```

### Opción 3: Git Push (Si el código está en git)

```bash
# Si los cambios están en git:
git add backend/app/api/routes_dashboard.py backend/app/services/signal_monitor.py
git commit -m "Fix: Auto-habilitar alert_enabled y usar strategy.decision en signal_monitor"
git push

# Luego en AWS:
ssh ubuntu@54.254.150.31
cd ~/automated-trading-platform
git pull
docker compose --profile aws restart backend
```

## ✅ Verificación Post-Despliegue

### 1. Verificar que los cambios están aplicados:
```bash
ssh ubuntu@54.254.150.31
docker compose --profile aws exec backend grep -A 3 "strategy.decision" /app/app/services/signal_monitor.py
```

Deberías ver algo como:
```python
elif strategy_decision:
    # CRITICAL: Use strategy.decision as primary source
    buy_signal = (strategy_decision == "BUY")
```

### 2. Verificar en el Dashboard:
- Abre: https://dashboard.hilovivo.com
- Busca BTC o DOT en la watchlist
- Verifica que muestra BUY con INDEX:100% (si las condiciones se cumplen)
- Verifica flags: `alert_enabled=YES`, `buy_alert_enabled=YES`, `trade_enabled=YES`

### 3. Probar el Fix:
1. Cambia `trade_enabled` de NO → YES para un símbolo (ej: DOT)
2. Verifica en los logs que se habilitan automáticamente los 3 flags
3. Si hay señal BUY válida, espera 30 segundos (próximo ciclo de signal_monitor)
4. La alerta debería saltar automáticamente

## 📋 Resumen de los Fixes

### Fix 1: Auto-habilitar `alert_enabled`
**Problema**: Al cambiar `trade_enabled` a YES, faltaba habilitar `alert_enabled` (master switch)
**Solución**: Ahora se habilita automáticamente junto con `buy_alert_enabled` y `sell_alert_enabled`

### Fix 2: Usar `strategy.decision` en signal_monitor
**Problema**: Dashboard mostraba BUY pero signal_monitor no detectaba la señal
**Solución**: signal_monitor ahora usa `strategy.decision` como fuente primaria (igual que dashboard)

## 🔍 Logs para Monitorear

Después del reinicio, monitorea los logs:
```bash
docker compose --profile aws logs -f backend | grep -E "(strategy.decision|BUY signal|signal_monitor)"
```

Deberías ver mensajes como:
```
✅ BTC_USDT using strategy.decision=BUY (matches dashboard): buy_signal=True
🟢 BUY signal detected for BTC_USDT
```
















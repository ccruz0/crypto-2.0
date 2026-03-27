# Instrucciones de Deploy

## ⚠️ Problema de Conexión

El script `sync_to_aws.sh` no puede conectarse a AWS (timeout en SSH).

## 🚀 Opciones de Deploy

### Opción 1: Deploy via GitHub Actions (Recomendado)

Hacer commit y push a `main`:

```bash
# Agregar cambios
git add backend/app/services/telegram_notifier.py \
        backend/app/services/signal_monitor.py \
        backend/app/api/routes_dashboard.py \
        docker-compose.yml

# Commit
git commit -m "Fix: Telegram SL/TP notifications + Manual signals support + Active orders filter

- Fix: send_sl_tp_orders() ahora pasa origin=get_runtime_origin() explícitamente
- Feature: Soporte para señales manuales desde dashboard (watchlist_item.signals)
- Fix: Solo contar órdenes TP activas (excluir CANCELLED/FILLED)
- Config: Agregado RUNTIME_ORIGIN al servicio backend en docker-compose.yml"

# Push a main (dispara GitHub Actions)
git push origin main
```

El workflow `.github/workflows/deploy.yml` se ejecutará automáticamente y:
1. Hace checkout del código
2. Ejecuta audit de trading pairs
3. Sincroniza archivos a AWS
4. Reinicia servicios con `docker compose --profile aws`

### Opción 2: Deploy Manual (si SSH está disponible)

Si puedes conectarte a AWS manualmente:

```bash
# 1. Hacer commit local
git add backend/app/services/telegram_notifier.py \
        backend/app/services/signal_monitor.py \
        backend/app/api/routes_dashboard.py \
        docker-compose.yml

git commit -m "Fix: Telegram SL/TP notifications + Manual signals support"

# 2. Push a main
git push origin main

# 3. En el servidor AWS, hacer pull y reiniciar:
ssh hilovivo-aws 'cd ~/crypto-2.0 && git pull origin main && docker compose --profile aws restart backend-aws'
```

### Opción 3: Deploy Solo Backend (si solo cambió backend)

```bash
# Copiar solo archivos del backend
rsync -avz --exclude='__pycache__' --exclude='*.pyc' \
  backend/app/services/telegram_notifier.py \
  backend/app/services/signal_monitor.py \
  backend/app/api/routes_dashboard.py \
  hilovivo-aws:~/crypto-2.0/backend/app/

# Reiniciar servicio
ssh hilovivo-aws 'cd ~/crypto-2.0 && docker compose --profile aws restart backend-aws'
```

## 📋 Cambios Incluidos en este Deploy

1. ✅ **Fix Telegram SL/TP**: `telegram_notifier.py` - Pasa `origin` explícitamente
2. ✅ **Señales Manuales**: `signal_monitor.py` - Usa señales del dashboard si están disponibles
3. ✅ **API Signals**: `routes_dashboard.py` - Incluye campo `signals` en serialización
4. ✅ **Órdenes Activas**: `routes_dashboard.py` - Solo cuenta órdenes TP activas
5. ✅ **Config Docker**: `docker-compose.yml` - Agregado `RUNTIME_ORIGIN` al servicio backend

## ✅ Verificación Post-Deploy

Después del deploy, verifica:

```bash
# 1. Servicios corriendo
ssh hilovivo-aws 'docker compose --profile aws ps'

# 2. Fix de Telegram aplicado
ssh hilovivo-aws 'docker compose --profile aws exec backend-aws python3 -c "from app.services.telegram_notifier import TelegramNotifier; import inspect; src = inspect.getsource(TelegramNotifier.send_sl_tp_orders); print(\"✅\" if \"origin=get_runtime_origin()\" in src else \"❌\")"'

# 3. Logs sin errores
ssh hilovivo-aws 'docker compose --profile aws logs backend-aws --tail 50'
```






# Cambios para Deploy

## 📋 Resumen de Cambios

### 1. **Fix: Notificaciones Telegram SL/TP** ✅
- **Archivo**: `backend/app/services/telegram_notifier.py`
- **Cambio**: `send_sl_tp_orders()` ahora pasa explícitamente `origin=get_runtime_origin()`
- **Línea**: ~902-907
- **Impacto**: Las notificaciones de SL/TP se enviarán correctamente cuando `RUNTIME_ORIGIN=AWS`

### 2. **Soporte para Señales Manuales desde Dashboard** ✅
- **Archivo**: `backend/app/services/signal_monitor.py`
- **Cambio**: Usa señales manuales de `watchlist_item.signals` si están disponibles
- **Línea**: ~912-924
- **Impacto**: Permite forzar `buy_signal=True` y `sell_signal=True` desde el dashboard

### 3. **API: Campo signals en Serialización** ✅
- **Archivo**: `backend/app/api/routes_dashboard.py`
- **Cambio**: Incluye campo `signals` en la serialización de watchlist items
- **Línea**: ~118
- **Impacto**: El dashboard puede leer y escribir señales manuales

### 4. **Fix: Contar Solo Órdenes Activas** ✅
- **Archivo**: `backend/app/api/routes_dashboard.py`
- **Cambio**: Solo cuenta órdenes TP con status activo (NEW, ACTIVE, PARTIALLY_FILLED)
- **Línea**: ~401-406, ~504-508
- **Impacto**: El dashboard muestra correctamente solo órdenes activas, excluyendo CANCELLED/FILLED

## 🚀 Proceso de Deploy

### Opción 1: Deploy Manual (sync_to_aws.sh)

```bash
./sync_to_aws.sh
```

Este script:
1. Construye imágenes Docker localmente
2. Las exporta a archivos tar.gz
3. Las copia a AWS
4. Reinicia los servicios en AWS

### Opción 2: Deploy via GitHub Actions

Hacer commit y push a `main`:

```bash
git add backend/app/services/telegram_notifier.py \
        backend/app/services/signal_monitor.py \
        backend/app/api/routes_dashboard.py

git commit -m "Fix: Telegram SL/TP notifications + Manual signals support + Active orders filter"

git push origin main
```

El workflow `.github/workflows/deploy.yml` se ejecutará automáticamente.

### Opción 3: Deploy Rápido (solo backend)

```bash
./deploy_to_aws.sh
```

## ✅ Verificación Post-Deploy

### 1. Verificar que el fix de Telegram está aplicado:
```bash
ssh hilovivo-aws 'cd ~/crypto-2.0 && docker compose --profile aws exec backend-aws python3 -c "from app.services.telegram_notifier import TelegramNotifier; import inspect; src = inspect.getsource(TelegramNotifier.send_sl_tp_orders); print(\"✅ Fix aplicado\" if \"origin=get_runtime_origin()\" in src or \"origin=origin\" in src else \"❌ Fix NO encontrado\")"'
```

### 2. Verificar que las señales manuales funcionan:
```bash
ssh hilovivo-aws 'cd ~/crypto-2.0 && docker compose --profile aws logs backend-aws | grep "using MANUAL signals" | tail -5'
```

### 3. Verificar servicios:
```bash
ssh hilovivo-aws 'cd ~/crypto-2.0 && docker compose --profile aws ps'
```

## 📝 Notas Importantes

- **Reinicio requerido**: Los cambios en el código requieren reiniciar el servicio `backend-aws`
- **Configuración**: Asegúrate de que `RUNTIME_ORIGIN=AWS` esté configurado en el servicio
- **Telegram**: Verifica que `TELEGRAM_BOT_TOKEN` y `TELEGRAM_CHAT_ID` estén configurados






# Configuración: Usar Solo Backend-AWS

## ✅ Configuración Aplicada

Has decidido usar **solo el servicio `backend-aws`** para evitar notificaciones duplicadas de Telegram.

## 📋 Pasos para Configurar

### Opción 1: Usar el Script Automático

```bash
./configurar_solo_aws.sh
```

### Opción 2: Pasos Manuales

1. **Detener servicios locales:**
   ```bash
   docker compose --profile local down
   ```

2. **Iniciar servicios AWS:**
   ```bash
   docker compose --profile aws up -d
   ```

3. **Verificar estado:**
   ```bash
   docker compose --profile aws ps
   ```

4. **Verificar configuración de Telegram:**
   ```bash
   docker compose --profile aws exec backend-aws env | grep -E "RUNTIME_ORIGIN|TELEGRAM|RUN_TELEGRAM"
   ```

   Deberías ver:
   ```
   RUNTIME_ORIGIN=AWS
   RUN_TELEGRAM=true
   TELEGRAM_BOT_TOKEN=...
   TELEGRAM_CHAT_ID=...
   ```

## ✅ Verificación del Fix

El fix ya está aplicado en el código (`backend/app/services/telegram_notifier.py`):
- ✅ `send_sl_tp_orders()` ahora pasa `origin=get_runtime_origin()`
- ✅ Con `RUNTIME_ORIGIN=AWS`, las notificaciones se enviarán correctamente

## 🔍 Monitoreo

Para verificar que las notificaciones funcionan:

```bash
# Monitorear logs en tiempo real
docker compose --profile aws logs -f backend-aws | grep -i "sl/tp\|telegram\|notification"

# Ver logs recientes
docker compose --profile aws logs --tail 100 backend-aws | grep -i "telegram"
```

## ⚠️ Importante

### Servicios que NO deben correr simultáneamente:

- ❌ **NO** tener `backend` (local) y `backend-aws` corriendo al mismo tiempo
- ✅ **SÍ** tener solo `backend-aws` corriendo

### Si necesitas cambiar entre perfiles:

**Para usar AWS (producción):**
```bash
docker compose --profile local down
docker compose --profile aws up -d
```

**Para usar Local (desarrollo):**
```bash
docker compose --profile aws down
docker compose --profile local up -d
```

## 📊 Estado Esperado

Después de la configuración, deberías tener:

```
✅ backend-aws: corriendo (perfil aws)
✅ RUNTIME_ORIGIN=AWS
✅ RUN_TELEGRAM=true
✅ TELEGRAM_BOT_TOKEN configurado
✅ TELEGRAM_CHAT_ID configurado
❌ backend: detenido (perfil local)
```

## 🎯 Resultado

- ✅ **Una sola notificación** por cada creación de SL/TP
- ✅ **Notificaciones funcionando** cuando `RUNTIME_ORIGIN=AWS`
- ✅ **Sin duplicados** porque solo hay un servicio procesando órdenes

## 🔧 Troubleshooting

### Si backend-aws no inicia:

1. Verificar que `.env.aws` existe y tiene las variables correctas
2. Verificar que `gluetun` (VPN) esté corriendo si es necesario
3. Ver logs: `docker compose --profile aws logs backend-aws`

### Si no recibes notificaciones:

1. Verificar configuración:
   ```bash
   docker compose --profile aws exec backend-aws env | grep TELEGRAM
   ```

2. Verificar logs:
   ```bash
   docker compose --profile aws logs backend-aws | grep -i "telegram\|gatekeeper"
   ```

3. Verificar que el fix está aplicado:
   ```bash
   docker compose --profile aws exec backend-aws python3 -c "from app.services.telegram_notifier import TelegramNotifier; import inspect; print(inspect.getsource(TelegramNotifier.send_sl_tp_orders))" | grep -i "origin"
   ```







# 📤 Enviar Mensaje de Prueba a Telegram

## 🚀 Ejecución Rápida en AWS

### Opción 1: Usando Docker Compose (Recomendado)

```bash
# Conecta a tu servidor AWS
ssh -i tu-key.pem ubuntu@tu-servidor-aws

# Navega al directorio del proyecto
cd ~/crypto-2.0

# Ejecuta el script
docker compose exec backend python scripts/send_test_message.py
```

### Opción 2: Ejecución Directa en el Servidor

```bash
# Conecta a tu servidor AWS
ssh -i tu-key.pem ubuntu@tu-servidor-aws

# Navega al directorio del proyecto
cd ~/crypto-2.0/backend

# Ejecuta el script directamente
python3 scripts/send_test_message.py
```

## 📋 Qué Verifica el Script

El script verifica y muestra:

1. ✅ **Runtime Origin** - Debe ser "AWS" para enviar mensajes
2. ✅ **Telegram Habilitado** - Estado de la configuración
3. ✅ **Bot Token** - Si está configurado
4. ✅ **Chat ID** - Si está configurado

## ✅ Resultado Esperado

Si todo está configurado correctamente, verás:

```
==========================================================
✅ ¡ÉXITO! Mensaje enviado correctamente
==========================================================

💡 Verifica tu chat de Telegram para confirmar la recepción.
```

Y recibirás un mensaje en Telegram que dice:

```
🧪 **MENSAJE DE PRUEBA**

Este es un mensaje de prueba del sistema de trading.

✅ **Estado del Sistema:**
   • Origen: AWS
   • Timestamp: [fecha y hora]
   • Sistema funcionando correctamente

Si recibes este mensaje, la configuración de Telegram está correcta.

🤖 Trading Bot Automático
```

## ❌ Si Hay Errores

El script mostrará información detallada sobre qué falta:

- **Telegram deshabilitado**: Verifica `RUN_TELEGRAM=true`
- **Bot Token no configurado**: Verifica `TELEGRAM_BOT_TOKEN` en `.env.local`
- **Chat ID no configurado**: Verifica `TELEGRAM_CHAT_ID` en `.env.local`
- **Runtime Origin incorrecto**: Verifica `RUNTIME_ORIGIN=AWS` en docker-compose.yml

## 🔧 Verificar Configuración Manualmente

Si quieres verificar la configuración antes de ejecutar:

```bash
# En AWS, verifica las variables de entorno
docker compose exec backend env | grep TELEGRAM
docker compose exec backend env | grep RUNTIME_ORIGIN
```

## 📝 Notas

- El script usa el mismo sistema que todos los demás mensajes de Telegram
- Si este mensaje funciona, todos los demás mensajes (alertas, resúmenes, etc.) también funcionarán
- El mensaje incluirá el prefijo `[AWS]` automáticamente

















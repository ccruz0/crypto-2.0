# Fix: Telegram Alerts No Llegan al Canal "Hilovivo-alerts"

## Problema Identificado

**Fecha**: 2025-12-27  
**Síntoma**: Las alertas se envían exitosamente según los logs, pero no llegan al canal "ilovivoalerts" en Telegram.

**Causa Raíz**: El `TELEGRAM_CHAT_ID` está configurado con un chat privado (`839853931`) en lugar del ID del canal "Hilovivo-alerts".

### Evidencia

1. **Logs muestran envío exitoso**:
   ```
   [TELEGRAM_SEND] type=ALERT symbol=BUY side=BUY chat_id=839853931 origin=AWS
   [TELEGRAM_RESPONSE] status=200 RESULT=SUCCESS message_id=6190
   ```

2. **Prueba de envío confirma**:
   ```json
   {
     "chat": {
       "id": 839853931,
       "first_name": "CARLOS",
       "username": "ccruz0",
       "type": "private"  // ❌ Es un chat privado, no un canal
     }
   }
   ```

3. **Configuración actual**:
   ```bash
   TELEGRAM_CHAT_ID=<REDACTED_TELEGRAM_CHAT_ID>
   ```

## Solución

### Paso 1: Obtener el Chat ID del Canal "Hilovivo-alerts"

Los canales de Telegram tienen IDs **negativos** (ejemplo: `-1001234567890`).

**Método A: Usando @userinfobot (RECOMENDADO)**
1. Abre Telegram y ve al canal "Hilovivo-alerts"
2. Reenvía cualquier mensaje del canal a `@userinfobot`
3. El bot te mostrará el chat_id (será un número negativo como `-1001234567890`)

**Método B: Usando la API de Telegram**
1. Asegúrate de que el bot esté agregado al canal "Hilovivo-alerts" como administrador
2. Envía un mensaje en el canal "Hilovivo-alerts"
3. Ejecuta:
   ```bash
   curl "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/getUpdates" | grep -o '"chat":{"id":-[0-9]*' | head -1
   ```

### Paso 2: Actualizar .env.aws en AWS

```bash
ssh hilovivo-aws
cd /home/ubuntu/automated-trading-platform
nano .env.aws
```

Cambia:
```bash
TELEGRAM_CHAT_ID=<REDACTED_TELEGRAM_CHAT_ID>
```

A:
```bash
TELEGRAM_CHAT_ID=<REDACTED_TELEGRAM_CHAT_ID>
```

### Paso 3: Reiniciar Servicios

```bash
docker compose --profile aws restart backend-aws
docker compose --profile aws restart market-updater-aws
```

### Paso 4: Verificar

```bash
# Verificar que el nuevo chat_id está cargado
docker compose --profile aws exec backend-aws env | grep TELEGRAM_CHAT_ID

# Ver logs de configuración
docker compose --profile aws logs backend-aws | grep TELEGRAM_CONFIG
```

Deberías ver:
```
[TELEGRAM_CONFIG] env=AWS resolved_channel=-1001234567890 label=ilovivoalerts
```

### Paso 5: Probar

1. Cambia `trade_amount_usd` de alguna moneda con señal activa
2. Verifica que la alerta llegue al canal "Hilovivo-alerts"
3. Revisa los logs para confirmar:
   ```
   [TELEGRAM_SEND] chat_id=-1001234567890
   [TELEGRAM_RESPONSE] status=200 RESULT=SUCCESS
   ```

## Notas Importantes

- **Chat IDs de canales son siempre negativos**: `-1001234567890`
- **Chat IDs de usuarios son positivos**: `839853931`
- El bot debe ser **administrador** del canal para poder enviar mensajes
- Los cambios en `.env.aws` requieren **reinicio** de servicios para aplicarse

## Estado Actual

- ✅ **Código funcionando**: El sistema detecta cambios de `config_hash` y envía alertas inmediatamente
- ✅ **Throttle reset funcionando**: `force_next_signal=True` se establece correctamente
- ✅ **Telegram API funcionando**: Los mensajes se envían exitosamente (status 200)
- ❌ **Canal incorrecto**: El `TELEGRAM_CHAT_ID` apunta a un chat privado en lugar del canal "Hilovivo-alerts"

## Próximos Pasos

1. Obtener el chat_id correcto del canal "Hilovivo-alerts"
2. Actualizar `.env.aws` con el chat_id correcto
3. Reiniciar servicios
4. Probar con una alerta real


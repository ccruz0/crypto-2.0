# 📱 Guía Paso a Paso: Configurar Telegram para Alertas Locales

## 🎯 Objetivo
Configurar Telegram para recibir alertas de trading en el entorno local con prefijo `[LOCAL]`.

---

## 📋 Paso 1: Obtener el Bot Token

### Si ya tienes un bot:
1. Abre Telegram y busca **@BotFather**
2. Envía el comando: `/mybots`
3. Selecciona tu bot
4. Elige **"API Token"**
5. Copia el token (formato: `<REDACTED_TELEGRAM_TOKEN>`)

### Si necesitas crear un bot nuevo:
1. Abre Telegram y busca **@BotFather**
2. Envía: `/newbot`
3. Sigue las instrucciones para darle un nombre
4. Copia el token que te proporciona

**⚠️ IMPORTANTE:** Guarda el token de forma segura. No lo compartas públicamente.

---

## 📋 Paso 2: Crear el Canal para Alertas Locales

1. Abre Telegram
2. Crea un **nuevo canal** (o grupo)
3. Nómbralo: `hilovivo-alerts-local` (o el nombre que prefieras)
4. Hazlo **público** o **privado** (ambos funcionan)

---

## 📋 Paso 3: Agregar el Bot al Canal

1. En el canal, ve a **"Administradores"** o **"Agregar miembros"**
2. Busca tu bot por su nombre (el que creaste con @BotFather)
3. Agrega el bot como **administrador**
4. Asegúrate de darle permisos para **"Enviar mensajes"**

---

## 📋 Paso 4: Obtener el Chat ID del Canal

### Método 1: Usando el Bot directamente (Más fácil)

1. Envía un mensaje cualquiera al canal (puede ser "test")
2. Abre tu navegador y visita esta URL (reemplaza `<BOT_TOKEN>` con tu token):
   ```
   https://api.telegram.org/bot<BOT_TOKEN>/getUpdates
   ```
   
   Ejemplo:
   ```
   https://api.telegram.org/bot1234567890:ABCdefGHIjklMNOpqrsTUVwxyz/getUpdates
   ```

3. Busca en el JSON la sección `"chat"` y copia el `"id"`
   - Para canales, será un número negativo como: `-1001234567890`
   - Para grupos, también será negativo
   - Para chats privados, será positivo

### Método 2: Usando curl desde terminal

```bash
# Reemplaza <BOT_TOKEN> con tu token real
curl "https://api.telegram.org/bot<BOT_TOKEN>/getUpdates" | python3 -m json.tool
```

Busca el `"id"` dentro de `"chat"`.

### Método 3: Usando otro bot helper

1. Busca **@userinfobot** en Telegram
2. Agrega el bot al canal
3. El bot te mostrará el Chat ID directamente

---

## 📋 Paso 5: Configurar el Archivo .env.local

1. Abre el archivo `.env.local` en tu editor:
   ```bash
   # Desde la terminal:
   nano .env.local
   # O usa tu editor favorito (VS Code, etc.)
   ```

2. Busca estas líneas (al final del archivo):
   ```bash
   # Telegram Configuration for Local Environment
   APP_ENV=local
   # TELEGRAM_BOT_TOKEN=your_bot_token_here
   # TELEGRAM_CHAT_ID=your_chat_id_here
   ```

3. Descomenta y completa con tus valores reales:
   ```bash
   # Telegram Configuration for Local Environment
   APP_ENV=local
   TELEGRAM_BOT_TOKEN=<REDACTED_TELEGRAM_TOKEN>
   TELEGRAM_CHAT_ID=<REDACTED_TELEGRAM_CHAT_ID>
   ```

   **Ejemplo real:**
   ```bash
   APP_ENV=local
   TELEGRAM_BOT_TOKEN=<REDACTED_TELEGRAM_TOKEN>
   TELEGRAM_CHAT_ID=<REDACTED_TELEGRAM_CHAT_ID>
   ```

4. Guarda el archivo

---

## 📋 Paso 6: Reiniciar el Servicio Backend

```bash
cd /Users/carloscruz/crypto-2.0
docker compose restart backend
```

Espera unos segundos a que el servicio se reinicie.

---

## 📋 Paso 7: Verificar la Configuración

Ejecuta este comando para verificar que todo está correcto:

```bash
docker compose exec backend python3 << 'EOF'
import sys
sys.path.insert(0, '/app')
from app.core.config import settings
from app.services.telegram_notifier import telegram_notifier
from app.services.telegram_notifier import get_app_env, AppEnv

print("=" * 60)
print("🔍 VERIFICACIÓN DE CONFIGURACIÓN TELEGRAM")
print("=" * 60)
print(f"\n📱 APP_ENV: {settings.APP_ENV or 'NO CONFIGURADO'}")
print(f"   Entorno detectado: {get_app_env().value}")

print(f"\n🤖 TELEGRAM_BOT_TOKEN:")
if settings.TELEGRAM_BOT_TOKEN:
    token_preview = settings.TELEGRAM_BOT_TOKEN[:10] + "..." + settings.TELEGRAM_BOT_TOKEN[-5:]
    print(f"   ✅ Configurado: {token_preview}")
else:
    print(f"   ❌ NO CONFIGURADO")

print(f"\n💬 TELEGRAM_CHAT_ID:")
if settings.TELEGRAM_CHAT_ID:
    print(f"   ✅ Configurado: {settings.TELEGRAM_CHAT_ID}")
else:
    print(f"   ❌ NO CONFIGURADO")

print(f"\n🔔 Telegram Notifier:")
print(f"   Enabled: {telegram_notifier.enabled}")
if telegram_notifier.enabled:
    print(f"   ✅ Telegram está ACTIVO y listo para enviar alertas")
    print(f"   📨 Las alertas se enviarán con prefijo: [LOCAL]")
else:
    print(f"   ❌ Telegram está DESACTIVADO")
    print(f"   ⚠️  Verifica que TELEGRAM_BOT_TOKEN y TELEGRAM_CHAT_ID estén configurados")

print("\n" + "=" * 60)
EOF
```

---

## 📋 Paso 8: Probar el Envío de Mensaje

Para probar que todo funciona, envía un mensaje de prueba:

```bash
docker compose exec backend python3 << 'EOF'
import sys
sys.path.insert(0, '/app')
from app.services.telegram_notifier import telegram_notifier

result = telegram_notifier.send_message("🧪 Mensaje de prueba desde entorno LOCAL")
if result:
    print("✅ Mensaje de prueba enviado exitosamente!")
    print("📱 Revisa el canal hilovivo-alerts-local en Telegram")
else:
    print("❌ Error al enviar mensaje de prueba")
    print("⚠️  Verifica la configuración")
EOF
```

Deberías ver el mensaje en tu canal con el prefijo `[LOCAL]`.

---

## ✅ Checklist Final

- [ ] Bot creado y token obtenido
- [ ] Canal `hilovivo-alerts-local` creado
- [ ] Bot agregado al canal como administrador
- [ ] Chat ID del canal obtenido
- [ ] Variables configuradas en `.env.local`
- [ ] Servicio backend reiniciado
- [ ] Verificación exitosa
- [ ] Mensaje de prueba enviado y recibido

---

## 🐛 Solución de Problemas

### ❌ "Telegram disabled: missing env vars"
**Solución:** Verifica que las variables en `.env.local` no tengan espacios extra y estén correctamente escritas.

### ❌ "Failed to send Telegram message"
**Solución:** 
- Verifica que el bot tenga permisos para enviar mensajes al canal
- Verifica que el Chat ID sea correcto (debe ser negativo para canales)
- Verifica que el Bot Token sea correcto

### ❌ "No se reciben mensajes"
**Solución:**
- Verifica que el bot esté agregado al canal
- Verifica que el Chat ID sea del canal correcto
- Revisa los logs: `docker compose logs backend | grep -i telegram`

### ❌ "El prefijo [LOCAL] no aparece"
**Solución:**
- Verifica que `APP_ENV=local` esté en `.env.local`
- Reinicia el servicio: `docker compose restart backend`

---

## 📚 Recursos Adicionales

- Documentación de Telegram Bot API: https://core.telegram.org/bots/api
- @BotFather en Telegram para gestionar bots
- Archivo de configuración: `CONFIGURAR_TELEGRAM_LOCAL.md`

---

## 🎉 ¡Listo!

Una vez completados todos los pasos, las alertas de BTC_USDT (y cualquier otra moneda con `alert_enabled=True`) se enviarán automáticamente al canal `hilovivo-alerts-local` con el prefijo `[LOCAL]`.


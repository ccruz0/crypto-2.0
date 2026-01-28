# Configurar Variables de Entorno Faltantes

**Fecha:** 2025-01-27  
**Estado:** ⚠️ Requiere acción manual

---

## ✅ Progreso Actual

- ✅ `SECRET_KEY` - **Ya generado automáticamente** por el script
- ✅ `TELEGRAM_CHAT_ID` - Ya configurado
- ✅ `POSTGRES_PASSWORD` - Ya configurado (pero revisar si es seguro)
- ❌ `OPENVPN_USER` - **FALTA**
- ❌ `OPENVPN_PASSWORD` - **FALTA**
- ❌ `TELEGRAM_BOT_TOKEN` - **FALTA**
- ❌ `CRYPTO_API_KEY` - **FALTA**
- ❌ `CRYPTO_API_SECRET` - **FALTA**
- ❌ `CRYPTO_PROXY_TOKEN` - **FALTA**

---

## 📝 Cómo Agregar las Variables Faltantes

### Opción 1: Editar .env.aws directamente

```bash
cd /Users/carloscruz/automated-trading-platform
nano .env.aws
```

Agrega las siguientes líneas al final del archivo:

```bash
# OpenVPN/NordVPN Credentials
OPENVPN_USER=tu_usuario_openvpn_aqui
OPENVPN_PASSWORD=tu_contraseña_openvpn_aqui

# Telegram Bot
TELEGRAM_BOT_TOKEN=<REDACTED_TELEGRAM_TOKEN>

# Crypto.com API
CRYPTO_API_KEY=tu_api_key_aqui
CRYPTO_API_SECRET=tu_api_secret_aqui
CRYPTO_PROXY_TOKEN=tu_proxy_token_aqui
```

### Opción 2: Usar el script de configuración

El script ya generó el `SECRET_KEY`. Ahora solo necesitas agregar las variables faltantes manualmente.

---

## 🔑 Dónde Obtener Cada Variable

### 1. OPENVPN_USER y OPENVPN_PASSWORD

**Fuente:** Tu cuenta de NordVPN

- Ve a tu cuenta de NordVPN
- Busca las credenciales de servicio (Service Credentials)
- O usa las credenciales que tenías antes (las que estaban hardcodeadas)

**Valores anteriores (para referencia, pero ROTAR):**
- `OPENVPN_USER=Jy4gvM3reuQn4FywkvSdfDBq`
- `OPENVPN_PASSWORD=VJy8dMvnvjdNERQQar8v5ESm`

⚠️ **IMPORTANTE:** Estas credenciales estaban expuestas. Se recomienda rotarlas.

---

### 2. TELEGRAM_BOT_TOKEN

**Fuente:** BotFather en Telegram

1. Abre Telegram
2. Busca `@BotFather`
3. Envía `/mybots`
4. Selecciona tu bot
5. Ve a "API Token" o "Edit Bot" > "Token"

**Valor anterior (para referencia, pero considerar rotar):**
- `TELEGRAM_BOT_TOKEN=<REDACTED_TELEGRAM_TOKEN>`

⚠️ **IMPORTANTE:** Este token estaba expuesto. Considera regenerarlo.

---

### 3. CRYPTO_API_KEY y CRYPTO_API_SECRET

**Fuente:** Tu cuenta de Crypto.com Exchange

1. Inicia sesión en [Crypto.com Exchange](https://crypto.com/exchange)
2. Ve a "API Management" o "Settings" > "API"
3. Crea una nueva API key o usa una existente
4. Copia la API Key y API Secret

⚠️ **IMPORTANTE:** 
- Guarda el API Secret inmediatamente (solo se muestra una vez)
- Configura los permisos necesarios (trading, lectura, etc.)

---

### 4. CRYPTO_PROXY_TOKEN

**Fuente:** Token de autenticación para el proxy de Crypto.com

Este es un token personalizado que usas para autenticar las peticiones al proxy.

**Valor anterior (para referencia):**
- `CRYPTO_PROXY_TOKEN=CRYPTO_PROXY_SECURE_TOKEN_2024`

Puedes:
- Usar el valor anterior si aún es válido
- Generar uno nuevo (cualquier string seguro y único)

Para generar uno nuevo:
```bash
python3 -c "import secrets; print(secrets.token_urlsafe(32))"
```

---

## ✅ Verificar Configuración

Después de agregar todas las variables, ejecuta:

```bash
cd /Users/carloscruz/automated-trading-platform
python3 scripts/validate_env_vars.py
```

Deberías ver:
```
✅ Validación exitosa - Todo está correctamente configurado
```

---

## 🔒 Seguridad

### ✅ Ya Configurado

- ✅ `.env.aws` está en `.gitignore` (no se subirá a git)
- ✅ `SECRET_KEY` generado automáticamente de forma segura
- ✅ Credenciales removidas de `docker-compose.yml`

### ⚠️ Acciones Recomendadas

1. **Rotar credenciales expuestas:**
   - OpenVPN: Generar nuevas credenciales en NordVPN
   - Telegram: Considerar regenerar el bot token
   - Crypto.com: Considerar crear nuevas API keys

2. **Verificar permisos de .env.aws:**
   ```bash
   chmod 600 .env.aws
   ```

3. **No compartir .env.aws:**
   - Nunca lo subas a git
   - No lo compartas por email/chat
   - Úsalo solo en el servidor de producción

---

## 📋 Checklist Final

- [ ] Agregar `OPENVPN_USER` a `.env.aws`
- [ ] Agregar `OPENVPN_PASSWORD` a `.env.aws`
- [ ] Agregar `TELEGRAM_BOT_TOKEN` a `.env.aws`
- [ ] Agregar `CRYPTO_API_KEY` a `.env.aws`
- [ ] Agregar `CRYPTO_API_SECRET` a `.env.aws`
- [ ] Agregar `CRYPTO_PROXY_TOKEN` a `.env.aws`
- [ ] Verificar permisos: `chmod 600 .env.aws`
- [ ] Ejecutar validación: `python3 scripts/validate_env_vars.py`
- [ ] (Opcional) Rotar credenciales expuestas

---

## 🆘 Ayuda

Si tienes problemas:

1. **Ver qué variables faltan:**
   ```bash
   bash scripts/setup_env_vars.sh
   ```

2. **Validar configuración:**
   ```bash
   python3 scripts/validate_env_vars.py
   ```

3. **Ver estructura de .env.aws (sin valores):**
   ```bash
   grep -E "^[A-Z_]+=" .env.aws | cut -d'=' -f1
   ```

---

**Fin del Documento**

















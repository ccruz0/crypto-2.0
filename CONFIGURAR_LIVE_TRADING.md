# 🚀 Configurar LIVE Trading (Órdenes Reales)

## ⚠️ ADVERTENCIA IMPORTANTE

**Las órdenes en modo LIVE usan dinero REAL.**
- Asegúrate de entender completamente el sistema antes de activarlo
- Recomendamos probar primero en DRY RUN
- Solo activa LIVE TRADING cuando estés seguro

## 📋 Requisitos

### 1. Credenciales de Crypto.com Exchange

1. Ve a https://exchange.crypto.com/
2. Inicia sesión en tu cuenta
3. Ve a **Settings → API Keys**
4. Crea una nueva API Key con los siguientes permisos:
   - ✅ **Read** (Lectura de datos)
   - ✅ **Trade** (Crear órdenes)
   - ❌ **Withdraw** (NO marcar - seguridad)
5. Copia tu **API Key** y **API Secret**
6. ⚠️ **IMPORTANTE**: Añade tu IP pública a la whitelist de la API Key

### 2. Obtener tu IP Pública

```bash
curl https://api.ipify.org
```

Anota esta IP para añadirla en Crypto.com Exchange.

## 🔧 Configuración Paso a Paso

### Opción 1: Script Automático (Recomendado)

```bash
# Desde la raíz del proyecto
docker compose exec backend python scripts/setup_live_trading.py
```

El script te guiará interactivamente para:
- Configurar tus credenciales
- Verificar la conexión
- Comprobar que todo funciona

### Opción 2: Configuración Manual

1. **Editar `.env.local`**:

```bash
# En la raíz del proyecto
nano .env.local
```

Añade o actualiza estas líneas:

```bash
LIVE_TRADING=true
USE_CRYPTO_PROXY=false
EXCHANGE_CUSTOM_API_KEY=tu_api_key_real_aqui
EXCHANGE_CUSTOM_API_SECRET=tu_api_secret_real_aqui
EXCHANGE_CUSTOM_BASE_URL=https://api.crypto.com/exchange/v1
```

**Reemplaza:**
- `tu_api_key_real_aqui` → Tu API Key real de Crypto.com
- `tu_api_secret_real_aqui` → Tu API Secret real de Crypto.com

2. **Reiniciar el backend**:

```bash
docker compose restart backend
```

3. **Verificar la conexión**:

```bash
docker compose exec backend python scripts/setup_live_trading.py
```

## ✅ Verificación

### Verificar que funciona:

1. **Comprobar configuración en el contenedor**:
```bash
docker compose exec backend python3 -c "import os; print('LIVE_TRADING:', os.getenv('LIVE_TRADING')); print('API Key configurada:', 'Sí' if os.getenv('EXCHANGE_CUSTOM_API_KEY') else 'No')"
```

2. **Probar crear una orden pequeña**:
   - Ve al Dashboard
   - Selecciona una moneda con Amount USD configurado
   - Haz clic en **BUY** o **SELL**
   - Confirma la orden
   - Verifica que aparece en tu cuenta de Crypto.com Exchange

3. **Verificar en Telegram**:
   - Deberías recibir una notificación cuando se crea la orden
   - El mensaje NO debería decir "🧪 (DRY RUN)"

## 🔒 Seguridad

### Recomendaciones:

1. **Usa una API Key con permisos limitados**:
   - ✅ Read: Necesario para leer balances
   - ✅ Trade: Necesario para crear órdenes
   - ❌ Withdraw: NO activar (seguridad)

2. **Whitelist de IP**:
   - Solo permite conexiones desde tu IP actual
   - Si cambias de red, actualiza la whitelist

3. **Monitorea tus órdenes**:
   - Revisa regularmente las órdenes creadas
   - Usa Stop Loss y Take Profit para proteger tus posiciones

4. **Empieza con cantidades pequeñas**:
   - Prueba con $10-50 USD primero
   - Aumenta gradualmente cuando estés seguro

## 🆘 Solución de Problemas

### Error: "Authentication failed (40101)"
- Verifica que las credenciales sean correctas
- Verifica que tu IP esté en la whitelist
- Verifica que la API Key tenga permisos de Trade

### Error: "IP illegal (40103)"
- Tu IP pública no está en la whitelist
- Obtén tu IP: `curl https://api.ipify.org`
- Añádela en Crypto.com Exchange → API Keys → Edit

### Las órdenes siguen siendo DRY RUN
- Verifica que `LIVE_TRADING=true` en `.env.local`
- Reinicia el backend: `docker compose restart backend`
- Verifica en el contenedor: `docker compose exec backend python3 -c "import os; print(os.getenv('LIVE_TRADING'))"`

## 📞 Soporte

Si tienes problemas, revisa los logs:
```bash
docker compose logs -f backend | grep -E "Authentication|Error|LIVE"
```


# 🔌 Configuración de Conexión a Crypto.com Exchange

Esta guía explica cómo configurar la conexión a Crypto.com Exchange API.

## 📋 Opciones de Conexión

Hay tres formas de conectar a Crypto.com Exchange:

### 1. 🔄 Conexión Directa (Recomendada)

Conexión directa sin proxy. Requiere que tu IP esté whitelisted en Crypto.com.

**Variables de entorno necesarias:**
```bash
USE_CRYPTO_PROXY=false
LIVE_TRADING=true
EXCHANGE_CUSTOM_API_KEY=tu_api_key
EXCHANGE_CUSTOM_API_SECRET=tu_api_secret
EXCHANGE_CUSTOM_BASE_URL=https://api.crypto.com/exchange/v1
```

### 2. 🛡️ Conexión a través de Proxy

Usa un proxy local para la autenticación. Requiere que el proxy esté corriendo.

**Variables de entorno necesarias:**
```bash
USE_CRYPTO_PROXY=true
CRYPTO_PROXY_URL=http://127.0.0.1:9000
CRYPTO_PROXY_TOKEN=tu_token_secreto
LIVE_TRADING=true
```

### 3. 🧪 Modo Dry-Run (Testing)

Modo simulado para pruebas sin conexión real.

**Variables de entorno:**
```bash
USE_CRYPTO_PROXY=false
LIVE_TRADING=false
```

## 🔧 Configuración Paso a Paso

### Paso 1: Obtener Credenciales de API

1. Inicia sesión en [Crypto.com Exchange](https://exchange.crypto.com/)
2. Ve a **API Keys** en la sección de configuración
3. Crea una nueva API Key con los siguientes permisos:
   - ✅ **Read** (para obtener balances y órdenes)
   - ✅ **Trade** (para colocar órdenes - opcional)
   - ✅ **Transfer** (para transferencias - opcional)
4. **IMPORTANTE**: Asegúrate de whitelist tu IP si usas conexión directa

### Paso 2: Configurar Variables de Entorno

Crea o edita el archivo `.env.local` (para desarrollo local):

```bash
# Conexión a Crypto.com Exchange
USE_CRYPTO_PROXY=false
LIVE_TRADING=true

# API Credentials
EXCHANGE_CUSTOM_API_KEY=tu_api_key_aqui
EXCHANGE_CUSTOM_API_SECRET=tu_api_secret_aqui

# Base URL (opcional, usa el default si no lo especificas)
EXCHANGE_CUSTOM_BASE_URL=https://api.crypto.com/exchange/v1
```

### Paso 3: Probar la Conexión

Ejecuta el script de prueba:

```bash
cd backend
python scripts/test_crypto_connection.py
```

Este script probará:
- ✅ Conexión a la API
- ✅ Obtención de balances
- ✅ Obtención de órdenes abiertas
- ✅ Obtención de historial de órdenes

### Paso 4: Verificar que el Servicio de Sincronización Funciona

Una vez configurado, el servicio de sincronización se iniciará automáticamente cuando el backend arranque.

Para verificar que está funcionando:

```bash
# Ver logs del backend
docker compose logs -f backend

# Deberías ver mensajes como:
# "Exchange sync service started"
# "Synced X account balances"
# "Synced X open orders"
```

## 🔍 Solución de Problemas

### Error: "Proxy connection refused"

**Causa**: El proxy no está corriendo y `USE_CRYPTO_PROXY=true`

**Solución**: 
1. Deshabilita el proxy: `USE_CRYPTO_PROXY=false`
2. O inicia el proxy en el puerto 9000

### Error: "Authentication failed (code: 40101)"

**Causa**: API Key o Secret incorrectos

**Solución**: 
1. Verifica que `EXCHANGE_CUSTOM_API_KEY` y `EXCHANGE_CUSTOM_API_SECRET` estén correctos
2. Regenera las credenciales en Crypto.com Exchange si es necesario

### Error: "IP illegal (code: 40103)"

**Causa**: Tu IP no está whitelisted en Crypto.com Exchange

**Solución**: 
1. Ve a la configuración de API Keys en Crypto.com Exchange
2. Agrega tu IP pública a la lista de IPs permitidas
3. Puedes obtener tu IP pública con: `curl https://api.ipify.org`

### Error: "Empty balance data"

**Causa**: La respuesta de la API no tiene el formato esperado

**Solución**: 
1. Verifica los logs del backend para ver la respuesta exacta
2. El servicio maneja múltiples formatos, pero si hay un formato nuevo, puede necesitar ajustes

## 📊 Estructura de Datos

Una vez configurado correctamente, los datos se almacenarán en:

- **`exchange_balances`**: Balances de tu cuenta (USDT, BTC, ETH, etc.)
- **`exchange_orders`**: Órdenes abiertas y ejecutadas
- **`trade_signals`**: Señales de trading calculadas

Puedes consultar estos datos a través del endpoint `/api/dashboard/state` o usando Telegram con `/portfolio`.

## ✅ Verificación Final

Una vez configurado, verifica que todo funciona:

1. ✅ El script de prueba pasa sin errores
2. ✅ Los balances aparecen en `/api/dashboard/state`
3. ✅ El comando `/portfolio` en Telegram muestra tus balances reales
4. ✅ Los logs del backend muestran "Synced X account balances" cada 5 segundos

## 🚀 Próximos Pasos

Una vez que la conexión funcione:
- Los balances se actualizarán automáticamente cada 5 segundos
- Las órdenes se sincronizarán automáticamente
- Podrás ver tu cartera en tiempo real en el dashboard


Esta guía explica cómo configurar la conexión a Crypto.com Exchange API.

## 📋 Opciones de Conexión

Hay tres formas de conectar a Crypto.com Exchange:

### 1. 🔄 Conexión Directa (Recomendada)

Conexión directa sin proxy. Requiere que tu IP esté whitelisted en Crypto.com.

**Variables de entorno necesarias:**
```bash
USE_CRYPTO_PROXY=false
LIVE_TRADING=true
EXCHANGE_CUSTOM_API_KEY=tu_api_key
EXCHANGE_CUSTOM_API_SECRET=tu_api_secret
EXCHANGE_CUSTOM_BASE_URL=https://api.crypto.com/exchange/v1
```

### 2. 🛡️ Conexión a través de Proxy

Usa un proxy local para la autenticación. Requiere que el proxy esté corriendo.

**Variables de entorno necesarias:**
```bash
USE_CRYPTO_PROXY=true
CRYPTO_PROXY_URL=http://127.0.0.1:9000
CRYPTO_PROXY_TOKEN=tu_token_secreto
LIVE_TRADING=true
```

### 3. 🧪 Modo Dry-Run (Testing)

Modo simulado para pruebas sin conexión real.

**Variables de entorno:**
```bash
USE_CRYPTO_PROXY=false
LIVE_TRADING=false
```

## 🔧 Configuración Paso a Paso

### Paso 1: Obtener Credenciales de API

1. Inicia sesión en [Crypto.com Exchange](https://exchange.crypto.com/)
2. Ve a **API Keys** en la sección de configuración
3. Crea una nueva API Key con los siguientes permisos:
   - ✅ **Read** (para obtener balances y órdenes)
   - ✅ **Trade** (para colocar órdenes - opcional)
   - ✅ **Transfer** (para transferencias - opcional)
4. **IMPORTANTE**: Asegúrate de whitelist tu IP si usas conexión directa

### Paso 2: Configurar Variables de Entorno

Crea o edita el archivo `.env.local` (para desarrollo local):

```bash
# Conexión a Crypto.com Exchange
USE_CRYPTO_PROXY=false
LIVE_TRADING=true

# API Credentials
EXCHANGE_CUSTOM_API_KEY=tu_api_key_aqui
EXCHANGE_CUSTOM_API_SECRET=tu_api_secret_aqui

# Base URL (opcional, usa el default si no lo especificas)
EXCHANGE_CUSTOM_BASE_URL=https://api.crypto.com/exchange/v1
```

### Paso 3: Probar la Conexión

Ejecuta el script de prueba:

```bash
cd backend
python scripts/test_crypto_connection.py
```

Este script probará:
- ✅ Conexión a la API
- ✅ Obtención de balances
- ✅ Obtención de órdenes abiertas
- ✅ Obtención de historial de órdenes

### Paso 4: Verificar que el Servicio de Sincronización Funciona

Una vez configurado, el servicio de sincronización se iniciará automáticamente cuando el backend arranque.

Para verificar que está funcionando:

```bash
# Ver logs del backend
docker compose logs -f backend

# Deberías ver mensajes como:
# "Exchange sync service started"
# "Synced X account balances"
# "Synced X open orders"
```

## 🔍 Solución de Problemas

### Error: "Proxy connection refused"

**Causa**: El proxy no está corriendo y `USE_CRYPTO_PROXY=true`

**Solución**: 
1. Deshabilita el proxy: `USE_CRYPTO_PROXY=false`
2. O inicia el proxy en el puerto 9000

### Error: "Authentication failed (code: 40101)"

**Causa**: API Key o Secret incorrectos

**Solución**: 
1. Verifica que `EXCHANGE_CUSTOM_API_KEY` y `EXCHANGE_CUSTOM_API_SECRET` estén correctos
2. Regenera las credenciales en Crypto.com Exchange si es necesario

### Error: "IP illegal (code: 40103)"

**Causa**: Tu IP no está whitelisted en Crypto.com Exchange

**Solución**: 
1. Ve a la configuración de API Keys en Crypto.com Exchange
2. Agrega tu IP pública a la lista de IPs permitidas
3. Puedes obtener tu IP pública con: `curl https://api.ipify.org`

### Error: "Empty balance data"

**Causa**: La respuesta de la API no tiene el formato esperado

**Solución**: 
1. Verifica los logs del backend para ver la respuesta exacta
2. El servicio maneja múltiples formatos, pero si hay un formato nuevo, puede necesitar ajustes

## 📊 Estructura de Datos

Una vez configurado correctamente, los datos se almacenarán en:

- **`exchange_balances`**: Balances de tu cuenta (USDT, BTC, ETH, etc.)
- **`exchange_orders`**: Órdenes abiertas y ejecutadas
- **`trade_signals`**: Señales de trading calculadas

Puedes consultar estos datos a través del endpoint `/api/dashboard/state` o usando Telegram con `/portfolio`.

## ✅ Verificación Final

Una vez configurado, verifica que todo funciona:

1. ✅ El script de prueba pasa sin errores
2. ✅ Los balances aparecen en `/api/dashboard/state`
3. ✅ El comando `/portfolio` en Telegram muestra tus balances reales
4. ✅ Los logs del backend muestran "Synced X account balances" cada 5 segundos

## 🚀 Próximos Pasos

Una vez que la conexión funcione:
- Los balances se actualizarán automáticamente cada 5 segundos
- Las órdenes se sincronizarán automáticamente
- Podrás ver tu cartera en tiempo real en el dashboard


Esta guía explica cómo configurar la conexión a Crypto.com Exchange API.

## 📋 Opciones de Conexión

Hay tres formas de conectar a Crypto.com Exchange:

### 1. 🔄 Conexión Directa (Recomendada)

Conexión directa sin proxy. Requiere que tu IP esté whitelisted en Crypto.com.

**Variables de entorno necesarias:**
```bash
USE_CRYPTO_PROXY=false
LIVE_TRADING=true
EXCHANGE_CUSTOM_API_KEY=tu_api_key
EXCHANGE_CUSTOM_API_SECRET=tu_api_secret
EXCHANGE_CUSTOM_BASE_URL=https://api.crypto.com/exchange/v1
```

### 2. 🛡️ Conexión a través de Proxy

Usa un proxy local para la autenticación. Requiere que el proxy esté corriendo.

**Variables de entorno necesarias:**
```bash
USE_CRYPTO_PROXY=true
CRYPTO_PROXY_URL=http://127.0.0.1:9000
CRYPTO_PROXY_TOKEN=tu_token_secreto
LIVE_TRADING=true
```

### 3. 🧪 Modo Dry-Run (Testing)

Modo simulado para pruebas sin conexión real.

**Variables de entorno:**
```bash
USE_CRYPTO_PROXY=false
LIVE_TRADING=false
```

## 🔧 Configuración Paso a Paso

### Paso 1: Obtener Credenciales de API

1. Inicia sesión en [Crypto.com Exchange](https://exchange.crypto.com/)
2. Ve a **API Keys** en la sección de configuración
3. Crea una nueva API Key con los siguientes permisos:
   - ✅ **Read** (para obtener balances y órdenes)
   - ✅ **Trade** (para colocar órdenes - opcional)
   - ✅ **Transfer** (para transferencias - opcional)
4. **IMPORTANTE**: Asegúrate de whitelist tu IP si usas conexión directa

### Paso 2: Configurar Variables de Entorno

Crea o edita el archivo `.env.local` (para desarrollo local):

```bash
# Conexión a Crypto.com Exchange
USE_CRYPTO_PROXY=false
LIVE_TRADING=true

# API Credentials
EXCHANGE_CUSTOM_API_KEY=tu_api_key_aqui
EXCHANGE_CUSTOM_API_SECRET=tu_api_secret_aqui

# Base URL (opcional, usa el default si no lo especificas)
EXCHANGE_CUSTOM_BASE_URL=https://api.crypto.com/exchange/v1
```

### Paso 3: Probar la Conexión

Ejecuta el script de prueba:

```bash
cd backend
python scripts/test_crypto_connection.py
```

Este script probará:
- ✅ Conexión a la API
- ✅ Obtención de balances
- ✅ Obtención de órdenes abiertas
- ✅ Obtención de historial de órdenes

### Paso 4: Verificar que el Servicio de Sincronización Funciona

Una vez configurado, el servicio de sincronización se iniciará automáticamente cuando el backend arranque.

Para verificar que está funcionando:

```bash
# Ver logs del backend
docker compose logs -f backend

# Deberías ver mensajes como:
# "Exchange sync service started"
# "Synced X account balances"
# "Synced X open orders"
```

## 🔍 Solución de Problemas

### Error: "Proxy connection refused"

**Causa**: El proxy no está corriendo y `USE_CRYPTO_PROXY=true`

**Solución**: 
1. Deshabilita el proxy: `USE_CRYPTO_PROXY=false`
2. O inicia el proxy en el puerto 9000

### Error: "Authentication failed (code: 40101)"

**Causa**: API Key o Secret incorrectos

**Solución**: 
1. Verifica que `EXCHANGE_CUSTOM_API_KEY` y `EXCHANGE_CUSTOM_API_SECRET` estén correctos
2. Regenera las credenciales en Crypto.com Exchange si es necesario

### Error: "IP illegal (code: 40103)"

**Causa**: Tu IP no está whitelisted en Crypto.com Exchange

**Solución**: 
1. Ve a la configuración de API Keys en Crypto.com Exchange
2. Agrega tu IP pública a la lista de IPs permitidas
3. Puedes obtener tu IP pública con: `curl https://api.ipify.org`

### Error: "Empty balance data"

**Causa**: La respuesta de la API no tiene el formato esperado

**Solución**: 
1. Verifica los logs del backend para ver la respuesta exacta
2. El servicio maneja múltiples formatos, pero si hay un formato nuevo, puede necesitar ajustes

## 📊 Estructura de Datos

Una vez configurado correctamente, los datos se almacenarán en:

- **`exchange_balances`**: Balances de tu cuenta (USDT, BTC, ETH, etc.)
- **`exchange_orders`**: Órdenes abiertas y ejecutadas
- **`trade_signals`**: Señales de trading calculadas

Puedes consultar estos datos a través del endpoint `/api/dashboard/state` o usando Telegram con `/portfolio`.

## ✅ Verificación Final

Una vez configurado, verifica que todo funciona:

1. ✅ El script de prueba pasa sin errores
2. ✅ Los balances aparecen en `/api/dashboard/state`
3. ✅ El comando `/portfolio` en Telegram muestra tus balances reales
4. ✅ Los logs del backend muestran "Synced X account balances" cada 5 segundos

## 🚀 Próximos Pasos

Una vez que la conexión funcione:
- Los balances se actualizarán automáticamente cada 5 segundos
- Las órdenes se sincronizarán automáticamente
- Podrás ver tu cartera en tiempo real en el dashboard


Esta guía explica cómo configurar la conexión a Crypto.com Exchange API.

## 📋 Opciones de Conexión

Hay tres formas de conectar a Crypto.com Exchange:

### 1. 🔄 Conexión Directa (Recomendada)

Conexión directa sin proxy. Requiere que tu IP esté whitelisted en Crypto.com.

**Variables de entorno necesarias:**
```bash
USE_CRYPTO_PROXY=false
LIVE_TRADING=true
EXCHANGE_CUSTOM_API_KEY=tu_api_key
EXCHANGE_CUSTOM_API_SECRET=tu_api_secret
EXCHANGE_CUSTOM_BASE_URL=https://api.crypto.com/exchange/v1
```

### 2. 🛡️ Conexión a través de Proxy

Usa un proxy local para la autenticación. Requiere que el proxy esté corriendo.

**Variables de entorno necesarias:**
```bash
USE_CRYPTO_PROXY=true
CRYPTO_PROXY_URL=http://127.0.0.1:9000
CRYPTO_PROXY_TOKEN=tu_token_secreto
LIVE_TRADING=true
```

### 3. 🧪 Modo Dry-Run (Testing)

Modo simulado para pruebas sin conexión real.

**Variables de entorno:**
```bash
USE_CRYPTO_PROXY=false
LIVE_TRADING=false
```

## 🔧 Configuración Paso a Paso

### Paso 1: Obtener Credenciales de API

1. Inicia sesión en [Crypto.com Exchange](https://exchange.crypto.com/)
2. Ve a **API Keys** en la sección de configuración
3. Crea una nueva API Key con los siguientes permisos:
   - ✅ **Read** (para obtener balances y órdenes)
   - ✅ **Trade** (para colocar órdenes - opcional)
   - ✅ **Transfer** (para transferencias - opcional)
4. **IMPORTANTE**: Asegúrate de whitelist tu IP si usas conexión directa

### Paso 2: Configurar Variables de Entorno

Crea o edita el archivo `.env.local` (para desarrollo local):

```bash
# Conexión a Crypto.com Exchange
USE_CRYPTO_PROXY=false
LIVE_TRADING=true

# API Credentials
EXCHANGE_CUSTOM_API_KEY=tu_api_key_aqui
EXCHANGE_CUSTOM_API_SECRET=tu_api_secret_aqui

# Base URL (opcional, usa el default si no lo especificas)
EXCHANGE_CUSTOM_BASE_URL=https://api.crypto.com/exchange/v1
```

### Paso 3: Probar la Conexión

Ejecuta el script de prueba:

```bash
cd backend
python scripts/test_crypto_connection.py
```

Este script probará:
- ✅ Conexión a la API
- ✅ Obtención de balances
- ✅ Obtención de órdenes abiertas
- ✅ Obtención de historial de órdenes

### Paso 4: Verificar que el Servicio de Sincronización Funciona

Una vez configurado, el servicio de sincronización se iniciará automáticamente cuando el backend arranque.

Para verificar que está funcionando:

```bash
# Ver logs del backend
docker compose logs -f backend

# Deberías ver mensajes como:
# "Exchange sync service started"
# "Synced X account balances"
# "Synced X open orders"
```

## 🔍 Solución de Problemas

### Error: "Proxy connection refused"

**Causa**: El proxy no está corriendo y `USE_CRYPTO_PROXY=true`

**Solución**: 
1. Deshabilita el proxy: `USE_CRYPTO_PROXY=false`
2. O inicia el proxy en el puerto 9000

### Error: "Authentication failed (code: 40101)"

**Causa**: API Key o Secret incorrectos

**Solución**: 
1. Verifica que `EXCHANGE_CUSTOM_API_KEY` y `EXCHANGE_CUSTOM_API_SECRET` estén correctos
2. Regenera las credenciales en Crypto.com Exchange si es necesario

### Error: "IP illegal (code: 40103)"

**Causa**: Tu IP no está whitelisted en Crypto.com Exchange

**Solución**: 
1. Ve a la configuración de API Keys en Crypto.com Exchange
2. Agrega tu IP pública a la lista de IPs permitidas
3. Puedes obtener tu IP pública con: `curl https://api.ipify.org`

### Error: "Empty balance data"

**Causa**: La respuesta de la API no tiene el formato esperado

**Solución**: 
1. Verifica los logs del backend para ver la respuesta exacta
2. El servicio maneja múltiples formatos, pero si hay un formato nuevo, puede necesitar ajustes

## 📊 Estructura de Datos

Una vez configurado correctamente, los datos se almacenarán en:

- **`exchange_balances`**: Balances de tu cuenta (USDT, BTC, ETH, etc.)
- **`exchange_orders`**: Órdenes abiertas y ejecutadas
- **`trade_signals`**: Señales de trading calculadas

Puedes consultar estos datos a través del endpoint `/api/dashboard/state` o usando Telegram con `/portfolio`.

## ✅ Verificación Final

Una vez configurado, verifica que todo funciona:

1. ✅ El script de prueba pasa sin errores
2. ✅ Los balances aparecen en `/api/dashboard/state`
3. ✅ El comando `/portfolio` en Telegram muestra tus balances reales
4. ✅ Los logs del backend muestran "Synced X account balances" cada 5 segundos

## 🚀 Próximos Pasos

Una vez que la conexión funcione:
- Los balances se actualizarán automáticamente cada 5 segundos
- Las órdenes se sincronizarán automáticamente
- Podrás ver tu cartera en tiempo real en el dashboard


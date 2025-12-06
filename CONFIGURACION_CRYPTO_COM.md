# 🚀 Guía Rápida: Configurar Conexión a Crypto.com Exchange

## 📍 Estado Actual

Tu configuración actual:
- ✅ **Sistema de sincronización**: Implementado y corriendo
- ⚠️ **Conexión**: Modo Dry-Run (datos simulados)
- ❌ **API Credentials**: No configuradas
- ❌ **Proxy**: No disponible (no está corriendo)

## 🎯 Opciones de Configuración

### Opción 1: Conexión Directa (Recomendada si tienes IP whitelisted)

**Pasos:**

1. **Obtener tus credenciales de API**:
   - Ve a https://exchange.crypto.com/
   - Settings → API Keys
   - Crea una nueva API Key con permisos de **Read** y **Trade**
   - Guarda el API Key y Secret

2. **Configurar variables de entorno**:

   Crea o edita `.env.local`:
   ```bash
   USE_CRYPTO_PROXY=false
   LIVE_TRADING=true
   EXCHANGE_CUSTOM_API_KEY=tu_api_key_aqui
   EXCHANGE_CUSTOM_API_SECRET=tu_api_secret_aqui
   EXCHANGE_CUSTOM_BASE_URL=https://api.crypto.com/exchange/v1
   ```

3. **Whitelist tu IP**:
   - Obtén tu IP pública: `curl https://api.ipify.org`
   - Agrega esta IP en la configuración de tu API Key en Crypto.com Exchange

4. **Reiniciar y probar**:
   ```bash
   docker compose restart backend
   docker compose exec backend python scripts/test_crypto_connection.py
   ```

### Opción 2: Usar Script de Configuración Automática

Usa el script interactivo que creé:

```bash
cd backend
./scripts/setup_crypto_connection.sh
```

Este script te guiará paso a paso para configurar la conexión.

### Opción 3: Modo Dry-Run (Testing)

Si solo quieres probar el sistema sin conexión real:

```bash
# Ya está configurado por defecto
USE_CRYPTO_PROXY=false
LIVE_TRADING=false
```

## ✅ Verificación

Una vez configurado, verifica que funciona:

1. **Verificar configuración**:
   ```bash
   docker compose exec backend python scripts/check_crypto_config.py
   ```

2. **Probar conexión**:
   ```bash
   docker compose exec backend python scripts/test_crypto_connection.py
   ```

3. **Verificar sincronización**:
   ```bash
   docker compose logs -f backend | grep "Synced"
   ```

4. **Ver balances en el endpoint**:
   ```bash
   curl http://localhost:8000/api/dashboard/state | jq '.balances'
   ```

5. **Ver cartera en Telegram**:
   Envía `/portfolio` a tu bot de Telegram

## 📋 Checklist de Configuración

- [ ] Credenciales de API obtenidas de Crypto.com Exchange
- [ ] IP pública whitelisted en Crypto.com (si usas conexión directa)
- [ ] Variables de entorno configuradas en `.env.local`
- [ ] Backend reiniciado: `docker compose restart backend`
- [ ] Prueba de conexión exitosa
- [ ] Balances apareciendo en `/api/dashboard/state`
- [ ] Servicio de sincronización funcionando (logs muestran "Synced X balances")

## 🔧 Solución de Problemas

### Error: "Authentication failed (40101)"
- Verifica que `EXCHANGE_CUSTOM_API_KEY` y `EXCHANGE_CUSTOM_API_SECRET` sean correctos
- Verifica que tu IP esté whitelisted

### Error: "IP illegal (40103)"
- Agrega tu IP pública a la lista de IPs permitidas en Crypto.com Exchange
- Obtén tu IP: `curl https://api.ipify.org`

### Error: "Proxy connection refused"
- Deshabilita el proxy: `USE_CRYPTO_PROXY=false`
- O inicia el proxy en el puerto 9000

### "Empty balance data"
- Verifica que tu cuenta tenga balances > 0
- Verifica los logs del backend para más detalles

## 📚 Documentación Adicional

- Ver `CRYPTO_COM_SETUP.md` para documentación detallada
- Ver `backend/README_MIGRATION.md` para información sobre la migración a DB

## 🚀 Próximos Pasos

Una vez configurado:
1. ✅ Los balances se sincronizarán automáticamente cada 5 segundos
2. ✅ Las órdenes se sincronizarán automáticamente
3. ✅ Podrás ver tu cartera en tiempo real con `/portfolio` en Telegram
4. ✅ El dashboard mostrará tus balances reales en `/api/dashboard/state`


## 📍 Estado Actual

Tu configuración actual:
- ✅ **Sistema de sincronización**: Implementado y corriendo
- ⚠️ **Conexión**: Modo Dry-Run (datos simulados)
- ❌ **API Credentials**: No configuradas
- ❌ **Proxy**: No disponible (no está corriendo)

## 🎯 Opciones de Configuración

### Opción 1: Conexión Directa (Recomendada si tienes IP whitelisted)

**Pasos:**

1. **Obtener tus credenciales de API**:
   - Ve a https://exchange.crypto.com/
   - Settings → API Keys
   - Crea una nueva API Key con permisos de **Read** y **Trade**
   - Guarda el API Key y Secret

2. **Configurar variables de entorno**:

   Crea o edita `.env.local`:
   ```bash
   USE_CRYPTO_PROXY=false
   LIVE_TRADING=true
   EXCHANGE_CUSTOM_API_KEY=tu_api_key_aqui
   EXCHANGE_CUSTOM_API_SECRET=tu_api_secret_aqui
   EXCHANGE_CUSTOM_BASE_URL=https://api.crypto.com/exchange/v1
   ```

3. **Whitelist tu IP**:
   - Obtén tu IP pública: `curl https://api.ipify.org`
   - Agrega esta IP en la configuración de tu API Key en Crypto.com Exchange

4. **Reiniciar y probar**:
   ```bash
   docker compose restart backend
   docker compose exec backend python scripts/test_crypto_connection.py
   ```

### Opción 2: Usar Script de Configuración Automática

Usa el script interactivo que creé:

```bash
cd backend
./scripts/setup_crypto_connection.sh
```

Este script te guiará paso a paso para configurar la conexión.

### Opción 3: Modo Dry-Run (Testing)

Si solo quieres probar el sistema sin conexión real:

```bash
# Ya está configurado por defecto
USE_CRYPTO_PROXY=false
LIVE_TRADING=false
```

## ✅ Verificación

Una vez configurado, verifica que funciona:

1. **Verificar configuración**:
   ```bash
   docker compose exec backend python scripts/check_crypto_config.py
   ```

2. **Probar conexión**:
   ```bash
   docker compose exec backend python scripts/test_crypto_connection.py
   ```

3. **Verificar sincronización**:
   ```bash
   docker compose logs -f backend | grep "Synced"
   ```

4. **Ver balances en el endpoint**:
   ```bash
   curl http://localhost:8000/api/dashboard/state | jq '.balances'
   ```

5. **Ver cartera en Telegram**:
   Envía `/portfolio` a tu bot de Telegram

## 📋 Checklist de Configuración

- [ ] Credenciales de API obtenidas de Crypto.com Exchange
- [ ] IP pública whitelisted en Crypto.com (si usas conexión directa)
- [ ] Variables de entorno configuradas en `.env.local`
- [ ] Backend reiniciado: `docker compose restart backend`
- [ ] Prueba de conexión exitosa
- [ ] Balances apareciendo en `/api/dashboard/state`
- [ ] Servicio de sincronización funcionando (logs muestran "Synced X balances")

## 🔧 Solución de Problemas

### Error: "Authentication failed (40101)"
- Verifica que `EXCHANGE_CUSTOM_API_KEY` y `EXCHANGE_CUSTOM_API_SECRET` sean correctos
- Verifica que tu IP esté whitelisted

### Error: "IP illegal (40103)"
- Agrega tu IP pública a la lista de IPs permitidas en Crypto.com Exchange
- Obtén tu IP: `curl https://api.ipify.org`

### Error: "Proxy connection refused"
- Deshabilita el proxy: `USE_CRYPTO_PROXY=false`
- O inicia el proxy en el puerto 9000

### "Empty balance data"
- Verifica que tu cuenta tenga balances > 0
- Verifica los logs del backend para más detalles

## 📚 Documentación Adicional

- Ver `CRYPTO_COM_SETUP.md` para documentación detallada
- Ver `backend/README_MIGRATION.md` para información sobre la migración a DB

## 🚀 Próximos Pasos

Una vez configurado:
1. ✅ Los balances se sincronizarán automáticamente cada 5 segundos
2. ✅ Las órdenes se sincronizarán automáticamente
3. ✅ Podrás ver tu cartera en tiempo real con `/portfolio` en Telegram
4. ✅ El dashboard mostrará tus balances reales en `/api/dashboard/state`


## 📍 Estado Actual

Tu configuración actual:
- ✅ **Sistema de sincronización**: Implementado y corriendo
- ⚠️ **Conexión**: Modo Dry-Run (datos simulados)
- ❌ **API Credentials**: No configuradas
- ❌ **Proxy**: No disponible (no está corriendo)

## 🎯 Opciones de Configuración

### Opción 1: Conexión Directa (Recomendada si tienes IP whitelisted)

**Pasos:**

1. **Obtener tus credenciales de API**:
   - Ve a https://exchange.crypto.com/
   - Settings → API Keys
   - Crea una nueva API Key con permisos de **Read** y **Trade**
   - Guarda el API Key y Secret

2. **Configurar variables de entorno**:

   Crea o edita `.env.local`:
   ```bash
   USE_CRYPTO_PROXY=false
   LIVE_TRADING=true
   EXCHANGE_CUSTOM_API_KEY=tu_api_key_aqui
   EXCHANGE_CUSTOM_API_SECRET=tu_api_secret_aqui
   EXCHANGE_CUSTOM_BASE_URL=https://api.crypto.com/exchange/v1
   ```

3. **Whitelist tu IP**:
   - Obtén tu IP pública: `curl https://api.ipify.org`
   - Agrega esta IP en la configuración de tu API Key en Crypto.com Exchange

4. **Reiniciar y probar**:
   ```bash
   docker compose restart backend
   docker compose exec backend python scripts/test_crypto_connection.py
   ```

### Opción 2: Usar Script de Configuración Automática

Usa el script interactivo que creé:

```bash
cd backend
./scripts/setup_crypto_connection.sh
```

Este script te guiará paso a paso para configurar la conexión.

### Opción 3: Modo Dry-Run (Testing)

Si solo quieres probar el sistema sin conexión real:

```bash
# Ya está configurado por defecto
USE_CRYPTO_PROXY=false
LIVE_TRADING=false
```

## ✅ Verificación

Una vez configurado, verifica que funciona:

1. **Verificar configuración**:
   ```bash
   docker compose exec backend python scripts/check_crypto_config.py
   ```

2. **Probar conexión**:
   ```bash
   docker compose exec backend python scripts/test_crypto_connection.py
   ```

3. **Verificar sincronización**:
   ```bash
   docker compose logs -f backend | grep "Synced"
   ```

4. **Ver balances en el endpoint**:
   ```bash
   curl http://localhost:8000/api/dashboard/state | jq '.balances'
   ```

5. **Ver cartera en Telegram**:
   Envía `/portfolio` a tu bot de Telegram

## 📋 Checklist de Configuración

- [ ] Credenciales de API obtenidas de Crypto.com Exchange
- [ ] IP pública whitelisted en Crypto.com (si usas conexión directa)
- [ ] Variables de entorno configuradas en `.env.local`
- [ ] Backend reiniciado: `docker compose restart backend`
- [ ] Prueba de conexión exitosa
- [ ] Balances apareciendo en `/api/dashboard/state`
- [ ] Servicio de sincronización funcionando (logs muestran "Synced X balances")

## 🔧 Solución de Problemas

### Error: "Authentication failed (40101)"
- Verifica que `EXCHANGE_CUSTOM_API_KEY` y `EXCHANGE_CUSTOM_API_SECRET` sean correctos
- Verifica que tu IP esté whitelisted

### Error: "IP illegal (40103)"
- Agrega tu IP pública a la lista de IPs permitidas en Crypto.com Exchange
- Obtén tu IP: `curl https://api.ipify.org`

### Error: "Proxy connection refused"
- Deshabilita el proxy: `USE_CRYPTO_PROXY=false`
- O inicia el proxy en el puerto 9000

### "Empty balance data"
- Verifica que tu cuenta tenga balances > 0
- Verifica los logs del backend para más detalles

## 📚 Documentación Adicional

- Ver `CRYPTO_COM_SETUP.md` para documentación detallada
- Ver `backend/README_MIGRATION.md` para información sobre la migración a DB

## 🚀 Próximos Pasos

Una vez configurado:
1. ✅ Los balances se sincronizarán automáticamente cada 5 segundos
2. ✅ Las órdenes se sincronizarán automáticamente
3. ✅ Podrás ver tu cartera en tiempo real con `/portfolio` en Telegram
4. ✅ El dashboard mostrará tus balances reales en `/api/dashboard/state`


## 📍 Estado Actual

Tu configuración actual:
- ✅ **Sistema de sincronización**: Implementado y corriendo
- ⚠️ **Conexión**: Modo Dry-Run (datos simulados)
- ❌ **API Credentials**: No configuradas
- ❌ **Proxy**: No disponible (no está corriendo)

## 🎯 Opciones de Configuración

### Opción 1: Conexión Directa (Recomendada si tienes IP whitelisted)

**Pasos:**

1. **Obtener tus credenciales de API**:
   - Ve a https://exchange.crypto.com/
   - Settings → API Keys
   - Crea una nueva API Key con permisos de **Read** y **Trade**
   - Guarda el API Key y Secret

2. **Configurar variables de entorno**:

   Crea o edita `.env.local`:
   ```bash
   USE_CRYPTO_PROXY=false
   LIVE_TRADING=true
   EXCHANGE_CUSTOM_API_KEY=tu_api_key_aqui
   EXCHANGE_CUSTOM_API_SECRET=tu_api_secret_aqui
   EXCHANGE_CUSTOM_BASE_URL=https://api.crypto.com/exchange/v1
   ```

3. **Whitelist tu IP**:
   - Obtén tu IP pública: `curl https://api.ipify.org`
   - Agrega esta IP en la configuración de tu API Key en Crypto.com Exchange

4. **Reiniciar y probar**:
   ```bash
   docker compose restart backend
   docker compose exec backend python scripts/test_crypto_connection.py
   ```

### Opción 2: Usar Script de Configuración Automática

Usa el script interactivo que creé:

```bash
cd backend
./scripts/setup_crypto_connection.sh
```

Este script te guiará paso a paso para configurar la conexión.

### Opción 3: Modo Dry-Run (Testing)

Si solo quieres probar el sistema sin conexión real:

```bash
# Ya está configurado por defecto
USE_CRYPTO_PROXY=false
LIVE_TRADING=false
```

## ✅ Verificación

Una vez configurado, verifica que funciona:

1. **Verificar configuración**:
   ```bash
   docker compose exec backend python scripts/check_crypto_config.py
   ```

2. **Probar conexión**:
   ```bash
   docker compose exec backend python scripts/test_crypto_connection.py
   ```

3. **Verificar sincronización**:
   ```bash
   docker compose logs -f backend | grep "Synced"
   ```

4. **Ver balances en el endpoint**:
   ```bash
   curl http://localhost:8000/api/dashboard/state | jq '.balances'
   ```

5. **Ver cartera en Telegram**:
   Envía `/portfolio` a tu bot de Telegram

## 📋 Checklist de Configuración

- [ ] Credenciales de API obtenidas de Crypto.com Exchange
- [ ] IP pública whitelisted en Crypto.com (si usas conexión directa)
- [ ] Variables de entorno configuradas en `.env.local`
- [ ] Backend reiniciado: `docker compose restart backend`
- [ ] Prueba de conexión exitosa
- [ ] Balances apareciendo en `/api/dashboard/state`
- [ ] Servicio de sincronización funcionando (logs muestran "Synced X balances")

## 🔧 Solución de Problemas

### Error: "Authentication failed (40101)"
- Verifica que `EXCHANGE_CUSTOM_API_KEY` y `EXCHANGE_CUSTOM_API_SECRET` sean correctos
- Verifica que tu IP esté whitelisted

### Error: "IP illegal (40103)"
- Agrega tu IP pública a la lista de IPs permitidas en Crypto.com Exchange
- Obtén tu IP: `curl https://api.ipify.org`

### Error: "Proxy connection refused"
- Deshabilita el proxy: `USE_CRYPTO_PROXY=false`
- O inicia el proxy en el puerto 9000

### "Empty balance data"
- Verifica que tu cuenta tenga balances > 0
- Verifica los logs del backend para más detalles

## 📚 Documentación Adicional

- Ver `CRYPTO_COM_SETUP.md` para documentación detallada
- Ver `backend/README_MIGRATION.md` para información sobre la migración a DB

## 🚀 Próximos Pasos

Una vez configurado:
1. ✅ Los balances se sincronizarán automáticamente cada 5 segundos
2. ✅ Las órdenes se sincronizarán automáticamente
3. ✅ Podrás ver tu cartera en tiempo real con `/portfolio` en Telegram
4. ✅ El dashboard mostrará tus balances reales en `/api/dashboard/state`


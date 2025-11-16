# 🔧 Troubleshooting: Error 40101 - Authentication Failure

## Estado Actual

- ✅ Credenciales configuradas: `z3HWF8m292zJKABkzfXWvQ`
- ✅ IP whitelisted: `86.48.10.82`
- ✅ Formato de firma verificado
- ❌ Error 40101 persiste: "Authentication failure"

## Diagnóstico

El error 40101 con la IP whitelisted típicamente indica:

### 1. Permisos de API Key ❌

**Problema**: La API Key no tiene permisos de "Read"

**Solución**:
1. Ve a https://exchange.crypto.com/
2. Settings → API Keys
3. Edita tu API Key `z3HWF8m292zJKABkzfXWvQ`
4. Verifica que "Read" esté habilitado
5. Si no lo está, habilítalo y guarda

### 2. Estado de API Key ❌

**Problema**: La API Key puede estar "Disabled" o "Suspended"

**Solución**:
1. Verifica el estado de tu API Key
2. Si está "Disabled", actívala
3. Si está "Suspended", contacta a Crypto.com Support

### 3. IP Whitelist ❌

**Problema**: La IP no está realmente whitelisted o tiene espacios

**Solución**:
1. Verifica que la IP sea exactamente: `86.48.10.82` (sin espacios)
2. Elimina la IP y agrégala de nuevo
3. Espera unos segundos para que se propague

### 4. Credenciales Incorrectas ❌

**Problema**: Las credenciales pueden estar incorrectas o revocadas

**Solución**:
1. Regenera la API Key completamente:
   - Elimina la API Key actual
   - Crea una nueva con permisos "Read" y "Trade"
   - Agrega tu IP inmediatamente
   - Copia las nuevas credenciales

2. Actualiza `.env.local`:
   ```bash
   EXCHANGE_CUSTOM_API_KEY=nueva_api_key
   EXCHANGE_CUSTOM_API_SECRET=nuevo_api_secret
   ```

3. Reinicia el backend:
   ```bash
   docker compose restart backend
   ```

## Verificación Final

Después de corregir el problema, verifica:

```bash
# Verificar configuración
docker compose exec backend python scripts/check_crypto_config.py

# Probar conexión
docker compose exec backend python scripts/test_crypto_connection.py

# Ver balances reales (no simulados)
curl http://localhost:8000/api/dashboard/state | jq '.balances'
```

Si ves balances reales (no USDT: 10000.0, BTC: 0.1), entonces funciona.

## Nota sobre Timestamp

El timestamp **NO es el problema**. El código genera el timestamp correctamente y está sincronizado.

El error 40101 es específicamente sobre autenticación de credenciales, no sobre tiempo.


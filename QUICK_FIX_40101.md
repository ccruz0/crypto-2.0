# 🔧 Solución Rápida: Error 40101 - Authentication Failure

## 🚀 Verificación Rápida

Ejecuta este script para diagnosticar el problema:

```bash
# En tu servidor AWS
docker compose exec backend python scripts/quick_check_auth.py
```

O si estás en el servidor directamente:

```bash
cd ~/automated-trading-platform/backend
python3 scripts/quick_check_auth.py
```

## 📋 Checklist de Verificación

El script verificará automáticamente:

1. ✅ **Credenciales configuradas** - `EXCHANGE_CUSTOM_API_KEY` y `EXCHANGE_CUSTOM_API_SECRET`
2. ✅ **Formato de credenciales** - Sin comillas, longitud correcta
3. ✅ **Configuración** - `LIVE_TRADING` y `USE_CRYPTO_PROXY`
4. ✅ **Conexión API** - Prueba real de autenticación

## 🔧 Soluciones Comunes para Error 40101

### 1. Verificar Permisos de API Key

**Problema más común**: La API key no tiene permiso "Read" habilitado.

**Solución**:
1. Ve a https://exchange.crypto.com/
2. Settings → API Keys
3. Edita tu API Key
4. **Asegúrate de que "Read" esté habilitado** ✅
5. Guarda los cambios

### 2. Verificar Estado de API Key

**Problema**: La API key está deshabilitada o suspendida.

**Solución**:
1. Verifica el estado de tu API key en Crypto.com Exchange
2. Debe estar "Active" (no "Disabled" o "Suspended")
3. Si está suspendida, contacta a Crypto.com Support

### 3. Verificar Credenciales

**Problema**: Las credenciales no coinciden exactamente.

**Solución**:
1. Verifica que `EXCHANGE_CUSTOM_API_KEY` coincida exactamente con tu API key
2. Verifica que `EXCHANGE_CUSTOM_API_SECRET` coincida exactamente con tu secret
3. **Sin espacios adicionales** ni caracteres ocultos
4. **Sin comillas** alrededor de los valores

### 4. Verificar IP Whitelist

**Problema**: La IP del servidor no está whitelisted (aunque esto causaría error 40103, no 40101).

**Solución**:
1. Obtén la IP de tu servidor: `curl https://api.ipify.org`
2. Agrega esta IP a la whitelist en Crypto.com Exchange API Key settings

## 🔄 Después de Corregir

1. **Reinicia el backend**:
   ```bash
   docker compose restart backend
   ```

2. **Verifica que funciona**:
   ```bash
   docker compose exec backend python scripts/quick_check_auth.py
   ```

3. **Prueba el resumen diario**:
   El próximo resumen diario debería funcionar correctamente.

## 📊 Verificación Adicional

Si el script rápido no resuelve el problema, ejecuta el diagnóstico completo:

```bash
docker compose exec backend python scripts/diagnose_auth_40101.py
```

Este script proporciona información más detallada sobre el problema.

## 💡 Notas Importantes

- **Error 40101** = Problema de autenticación (credenciales o permisos)
- **Error 40103** = IP no whitelisted
- Los cambios en Crypto.com Exchange pueden tardar unos segundos en aplicarse
- Asegúrate de reiniciar el backend después de cambiar variables de entorno

## 🆘 Si Nada Funciona

1. Regenera completamente la API key:
   - Elimina la API key actual en Crypto.com Exchange
   - Crea una nueva con permisos "Read" y "Trade"
   - Agrega tu IP a la whitelist inmediatamente
   - Actualiza las credenciales en `.env.local`
   - Reinicia el backend

2. Verifica los logs para más detalles:
   ```bash
   docker compose logs backend | grep -i "40101\|authentication\|crypto"
   ```

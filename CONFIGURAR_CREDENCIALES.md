# 🔑 Configurar Credenciales de Crypto.com Exchange

## Pasos Rápidos

### 1. Crear archivo `.env.local`

Crea el archivo `.env.local` en la raíz del proyecto con el siguiente contenido:

```bash
USE_CRYPTO_PROXY=false
LIVE_TRADING=true
EXCHANGE_CUSTOM_API_KEY=tu_api_key_aqui
EXCHANGE_CUSTOM_API_SECRET=tu_api_secret_aqui
EXCHANGE_CUSTOM_BASE_URL=https://api.crypto.com/exchange/v1
```

**Reemplaza:**
- `tu_api_key_aqui` → Tu API Key de Crypto.com Exchange
- `tu_api_secret_aqui` → Tu API Secret de Crypto.com Exchange

### 2. Whitelist tu IP

Tu IP pública actual es: **86.48.10.82**

1. Ve a https://exchange.crypto.com/
2. Settings → API Keys
3. Edita tu API Key
4. Agrega esta IP a la lista de IPs permitidas: `86.48.10.82`

### 3. Reiniciar y Probar

```bash
# Reiniciar el backend para cargar las nuevas variables
docker compose restart backend

# Esperar unos segundos y luego probar la conexión
docker compose exec backend python scripts/test_crypto_connection.py
```

### 4. Verificar que Funciona

```bash
# Ver configuración
docker compose exec backend python scripts/check_crypto_config.py

# Ver balances sincronizados
curl http://localhost:8000/api/dashboard/state | jq '.balances'

# Ver en Telegram
# Envía /portfolio a tu bot
```

## ✅ Checklist

- [ ] Archivo `.env.local` creado con tus credenciales
- [ ] IP `86.48.10.82` agregada a whitelist en Crypto.com Exchange
- [ ] Backend reiniciado
- [ ] Prueba de conexión exitosa
- [ ] Balances aparecen en `/api/dashboard/state`

## 🔍 Solución de Problemas

### Error: "Authentication failed (40101)"
- Verifica que las credenciales sean correctas
- Verifica que tu IP esté whitelisted

### Error: "IP illegal (40103)"
- Asegúrate de haber agregado tu IP `86.48.10.82` en Crypto.com Exchange
- Si cambias de red, actualiza la IP en Crypto.com

### No aparecen balances
- Verifica que tu cuenta tenga balances > 0
- Revisa los logs: `docker compose logs -f backend | grep "Synced"`


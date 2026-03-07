# 🔌 Conexión AWS → Crypto.com Exchange: Guía Completa

## 📋 Resumen Ejecutivo

**Esta es la configuración estándar y debe usarse siempre en producción AWS.**

El backend en AWS se conecta **directamente** a Crypto.com Exchange API usando la **IP Elástica de AWS**, sin necesidad de VPN, proxy o servicios intermedios.

---

## 🏗️ Arquitectura de Conexión

### Diagrama de Flujo

```
┌─────────────────┐
│  Backend AWS    │
│  (Docker)       │
└────────┬────────┘
         │ HTTPS
         │
         ▼
┌─────────────────┐
│  AWS Elastic IP │
│  52.220.32.147  │
└────────┬────────┘
         │ HTTPS
         │
         ▼
┌─────────────────┐
│ Crypto.com      │
│ Exchange API v1 │
│ api.crypto.com  │
└─────────────────┘
```

### Características Clave

- ✅ **Conexión Directa**: Sin VPN, sin proxy, sin intermediarios
- ✅ **IP Fija**: AWS Elastic IP garantiza IP consistente
- ✅ **Baja Latencia**: Conexión directa reduce overhead
- ✅ **Costo Eficiente**: No requiere servicios de VPN dedicados
- ✅ **API v1**: Usa `https://api.crypto.com/exchange/v1` (no v2)

---

## ⚙️ Configuración Requerida

### 1. Variables de Entorno en `.env.aws`

**ESTAS VARIABLES DEBEN ESTAR SIEMPRE CONFIGURADAS ASÍ:**

```bash
# ============================================
# CONEXIÓN CRYPTO.COM - CONFIGURACIÓN ESTÁNDAR
# ============================================

# Conexión directa (SIN proxy, SIN VPN)
USE_CRYPTO_PROXY=false

# Trading en vivo activado
LIVE_TRADING=true

# API Endpoint de Crypto.com Exchange v1
EXCHANGE_CUSTOM_BASE_URL=https://api.crypto.com/exchange/v1
CRYPTO_REST_BASE=https://api.crypto.com/exchange/v1

# Credenciales de API (obtenidas de Crypto.com Exchange)
EXCHANGE_CUSTOM_API_KEY=tu_api_key_aqui
EXCHANGE_CUSTOM_API_SECRET=tu_api_secret_aqui
```

### 2. Configuración en `docker-compose.yml`

El servicio `backend-aws` debe tener esta configuración:

```yaml
backend-aws:
  environment:
    # Conexión directa a Crypto.com
    - USE_CRYPTO_PROXY=${USE_CRYPTO_PROXY:-false}  # Default: false
    - LIVE_TRADING=${LIVE_TRADING:-true}
    - EXCHANGE_CUSTOM_BASE_URL=https://api.crypto.com/exchange/v1
    - CRYPTO_REST_BASE=https://api.crypto.com/exchange/v1
  depends_on:
    db:
      condition: service_healthy
    # NO debe depender de gluetun o proxy
```

### 3. Whitelist de IP en Crypto.com

**PASO CRÍTICO**: La IP de salida de AWS debe estar whitelisted en Crypto.com Exchange.

**Producción (atp-rebuild-2026):** usa la IP **52.220.32.147**. El backend la registra en logs como `CRYPTO_COM_OUTBOUND_IP: 52.220.32.147`. Whitelist **esa IP exacta** en la API key de Crypto.com Exchange.

1. Comprobar IP de salida (opcional):
   ```bash
   # Desde la instancia AWS
   curl https://api.ipify.org
   # Producción: 52.220.32.147
   ```

2. En Crypto.com Exchange:
   - Ve a https://exchange.crypto.com/
   - Settings → API Management (o API Keys)
   - Edita tu API Key
   - En IP Whitelist, agrega **52.220.32.147**

---

## 🚀 Proceso de Configuración Paso a Paso

### Paso 1: Verificar IP de salida (producción)

```bash
# Conectarse a la instancia AWS (producción atp-rebuild-2026)
ssh ubuntu@52.220.32.147

# Verificar IP pública
curl https://api.ipify.org
```

**Resultado esperado**: Debe mostrar **52.220.32.147** (o la IP que aparezca en logs como `CRYPTO_COM_OUTBOUND_IP`)

### Paso 2: Configurar Variables de Entorno

Edita `.env.aws` en la instancia AWS:

```bash
cd ~/automated-trading-platform
nano .env.aws
```

Asegúrate de que contenga:

```bash
USE_CRYPTO_PROXY=false
LIVE_TRADING=true
EXCHANGE_CUSTOM_BASE_URL=https://api.crypto.com/exchange/v1
CRYPTO_REST_BASE=https://api.crypto.com/exchange/v1
EXCHANGE_CUSTOM_API_KEY=tu_api_key_real
EXCHANGE_CUSTOM_API_SECRET=tu_api_secret_real
```

### Paso 3: Whitelist IP en Crypto.com

1. Inicia sesión en https://exchange.crypto.com/
2. Ve a **Settings** → **API Management** (o API Keys)
3. Selecciona tu API Key
4. En **IP Whitelist**, agrega **52.220.32.147** (producción AWS)
5. Guarda los cambios

### Paso 4: Reiniciar Servicios

```bash
# Reiniciar backend para aplicar cambios
docker compose --profile aws restart backend-aws

# Verificar que está corriendo
docker compose --profile aws ps backend-aws
```

### Paso 5: Verificar Conexión

```bash
# Probar conexión a Crypto.com
docker compose --profile aws exec backend-aws python scripts/test_crypto_connection.py

# Verificar logs
docker compose --profile aws logs backend-aws --tail 50 | grep -i crypto
```

**Resultado esperado**: Debe mostrar conexión exitosa sin errores de autenticación.

---

## ✅ Verificación de Configuración Correcta

### Checklist de Verificación

- [ ] `USE_CRYPTO_PROXY=false` en `.env.aws`
- [ ] `LIVE_TRADING=true` en `.env.aws`
- [ ] `EXCHANGE_CUSTOM_BASE_URL` apunta a `https://api.crypto.com/exchange/v1`
- [ ] Credenciales de API configuradas en `.env.aws`
- [ ] IP **52.220.32.147** whitelisted en Crypto.com Exchange (API key)
- [ ] Backend reiniciado después de cambios
- [ ] Test de conexión exitoso

### Comandos de Verificación

```bash
# 1. Verificar variables de entorno
docker compose --profile aws exec backend-aws env | grep -E 'USE_CRYPTO_PROXY|LIVE_TRADING|EXCHANGE_CUSTOM'

# 2. Verificar IP de salida
docker compose --profile aws exec backend-aws python -c "import requests; print('Outbound IP:', requests.get('https://api.ipify.org').text)"

# 3. Probar conexión
docker compose --profile aws exec backend-aws python scripts/test_crypto_connection.py

# 4. Verificar logs de inicialización
docker compose --profile aws logs backend-aws --tail 100 | grep -i "CryptoComTradeClient\|USE_CRYPTO_PROXY\|base URL"
```

**Resultados esperados:**

1. Variables de entorno:
   ```
   USE_CRYPTO_PROXY=false
   LIVE_TRADING=true
   EXCHANGE_CUSTOM_BASE_URL=https://api.crypto.com/exchange/v1
   ```

2. IP de salida: Producción = **52.220.32.147** (CRYPTO_COM_OUTBOUND_IP en logs)

3. Test de conexión: Debe mostrar éxito sin errores

4. Logs: Debe mostrar:
   ```
   CryptoComTradeClient initialized - Live Trading: True
   Using base URL: https://api.crypto.com/exchange/v1
   ```

---

## 🔧 Troubleshooting

### Problema: Error 40101 (Authentication Failure)

**Causa**: IP no whitelisted o credenciales incorrectas

**Solución**:
1. Verificar que la IP Elástica esté en la whitelist de Crypto.com
2. Verificar credenciales en `.env.aws`
3. Reiniciar backend después de cambios

### Problema: Backend usa proxy en lugar de conexión directa

**Causa**: `USE_CRYPTO_PROXY=true` o variable no configurada

**Solución**:
```bash
# Verificar valor actual
docker compose --profile aws exec backend-aws env | grep USE_CRYPTO_PROXY

# Si muestra 'true', actualizar .env.aws
echo "USE_CRYPTO_PROXY=false" >> .env.aws

# Reiniciar
docker compose --profile aws restart backend-aws
```

### Problema: Backend depende de gluetun

**Causa**: `docker-compose.yml` tiene dependencia de gluetun

**Solución**:
1. Editar `docker-compose.yml`
2. Remover `gluetun` de `depends_on` en `backend-aws`
3. Reiniciar servicio

---

## 📝 Mejores Prácticas

### ✅ HACER SIEMPRE

1. **Usar conexión directa**: `USE_CRYPTO_PROXY=false` siempre en AWS
2. **IP Elástica**: Usar siempre IP Elástica de AWS (no IP dinámica)
3. **API v1**: Usar siempre `https://api.crypto.com/exchange/v1` (no v2)
4. **Verificar whitelist**: Asegurar que la IP esté whitelisted antes de desplegar
5. **Logs de verificación**: Revisar logs después de cambios de configuración

### ❌ NUNCA HACER

1. **No usar proxy en AWS**: No configurar `USE_CRYPTO_PROXY=true` en producción AWS
2. **No usar VPN**: No depender de gluetun o NordVPN para conexión a Crypto.com
3. **No usar API v2**: No usar `https://api.crypto.com/v2` (deprecated)
4. **No cambiar IP frecuentemente**: Mantener IP Elástica estable
5. **No exponer credenciales**: No commitear `.env.aws` con credenciales reales

---

## 🔄 Proceso de Actualización

Cuando necesites actualizar la configuración:

1. **Editar `.env.aws`** con nuevos valores
2. **Verificar whitelist** en Crypto.com si cambias IP
3. **Reiniciar backend**: `docker compose --profile aws restart backend-aws`
4. **Verificar logs**: Confirmar que la nueva configuración se aplicó
5. **Probar conexión**: Ejecutar test de conexión

---

## 📚 Referencias

- **Documentación Crypto.com Exchange API**: https://exchange-docs.crypto.com/
- **AWS Elastic IP Setup**: `docs/AWS_ELASTIC_IP_SETUP.md`
- **Configuración Local**: `CRYPTO_COM_SETUP.md`
- **Migración Report**: `MIGRATION_TO_DIRECT_AWS_IP_REPORT.md`

---

## 🎯 Resumen Rápido

**Configuración estándar AWS → Crypto.com:**

```bash
# .env.aws
USE_CRYPTO_PROXY=false
LIVE_TRADING=true
EXCHANGE_CUSTOM_BASE_URL=https://api.crypto.com/exchange/v1
CRYPTO_REST_BASE=https://api.crypto.com/exchange/v1
EXCHANGE_CUSTOM_API_KEY=tu_key
EXCHANGE_CUSTOM_API_SECRET=tu_secret
```

**Arquitectura:**
```
Backend AWS → AWS Elastic IP → Crypto.com Exchange API v1
```

**Verificación:**
```bash
docker compose --profile aws exec backend-aws python scripts/test_crypto_connection.py
```

---

*Última actualización: 2025-12-19*
*Versión: 1.0*






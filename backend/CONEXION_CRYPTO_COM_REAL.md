# Conexión a Crypto.com - Modo Producción

## Estado Actual
❌ **Modo DRY_RUN activado** (simulación)  
❌ **API keys NO configuradas**  
❌ **Dashboard muestra solo datos simulados**  

## Objetivo
✅ Conectar a cuenta REAL de crypto.com  
✅ Mostrar órdenes abiertas reales en dashboard  
✅ Mostrar cartera real  
✅ Guardar historial de órdenes ejecutadas en BD  
✅ Sincronizar cada 60 segundos  

## Pasos para Configurar

### 1. Obtener API Keys de Crypto.com

1. **Login a crypto.com Exchange**
   - https://crypto.com/exchange/

2. **Ir a API Management**
   - Settings → API Management → Create New API Key

3. **Configurar Permisos**
   - ✅ **Read** - Para leer órdenes, balance, historial
   - ✅ **Trade** - Para crear/cancelar órdenes
   - ❌ **Withdraw** - NO necesario (más seguro no habilitarlo)

4. **Copiar Credenciales**
   - API Key (largo string de caracteres)
   - Secret Key (otro string largo)
   - **⚠️ GUÁRDALOS EN LUGAR SEGURO**

### 2. Configurar Variables de Entorno

**Archivo:** `.env` en la raíz del proyecto

```bash
cd /Users/carloscruz/automated-trading-platform
nano .env
```

**Agregar/modificar estas líneas:**
```env
# Crypto.com Exchange API
LIVE_TRADING=true
CRYPTO_COM_API_KEY=tu_api_key_aqui
CRYPTO_COM_SECRET_KEY=tu_secret_key_aqui

# Opcional (por defecto usa producción)
CRYPTO_COM_USE_SANDBOX=false
```

**⚠️ IMPORTANTE:**
- Las API keys deben ser de **PRODUCCIÓN**, no sandbox
- Asegúrate de no compartir estas keys
- No las subas a git (.env está en .gitignore)

### 3. Reiniciar Backend

```bash
cd /Users/carloscruz/automated-trading-platform
docker compose --profile local restart backend
```

Espera ~30 segundos hasta que el backend esté listo.

### 4. Verificar Conexión

```bash
# Health check
curl http://localhost:8002/health

# Verificar órdenes sincronizadas
curl http://localhost:8002/api/dashboard/state | jq '.open_orders | length'
```

Deberías ver el número real de órdenes de crypto.com.

## Qué Hace el Sistema Una Vez Configurado

### Sincronización Automática (Cada 60 Segundos)

**1. Órdenes Abiertas (Open Orders)**
- ✅ Llama a crypto.com API `get_open_orders()`
- ✅ Obtiene todas las órdenes activas
- ✅ Actualiza estado en BD
- ✅ Dashboard muestra en tiempo real

**2. Historial de Órdenes (Executed Orders)**
- ✅ Llama a crypto.com API `get_order_history()`
- ✅ Descarga órdenes FILLED/CANCELLED
- ✅ **Guarda en BD** (tabla `exchange_orders`)
- ✅ Detecta nuevas órdenes ejecutadas
- ✅ **Crea SL/TP automáticamente** si es orden BUY/SELL

**3. Balance de Cartera (Portfolio)**
- ✅ Llama a crypto.com API `get_account_summary()`
- ✅ Obtiene balance de todas las monedas
- ✅ Actualiza portfolio cache
- ✅ Dashboard muestra valor total USD

### Sistema OCO Automático

Cuando una orden se ejecuta:
1. **Detecta:** Orden BUY → FILLED
2. **Genera:** `oco_group_id` único
3. **Crea SL:** Stop Loss con `order_role="STOP_LOSS"`
4. **Crea TP:** Take Profit con `order_role="TAKE_PROFIT"`
5. **Guarda:** Ambas en BD con campos OCO
6. **Monitorea:** Cada 60s
7. **Cancela:** Cuando una se ejecuta, cancela la otra

## Dashboard - Origen de Datos

### Con LIVE_TRADING=true

| Sección | Origen | Frecuencia |
|---------|--------|------------|
| **Open Orders** | crypto.com API | Tiempo real (sync 60s) |
| **Portfolio** | crypto.com API | Tiempo real (sync 60s) |
| **Executed Orders** | Base de datos | Histórico completo |
| **Watchlist** | Base de datos | Manual/configurado |
| **Signals** | Base de datos | Calculado cada 5 min |

### Flujo de Datos

```
crypto.com Exchange (cuenta real)
    ↓ (cada 60s)
Exchange Sync Service
    ↓
Base de Datos PostgreSQL
    ↓
Dashboard API (/api/dashboard/state)
    ↓
Frontend (React)
```

## Seguridad

### API Keys
- ✅ Almacenadas en `.env` (no en git)
- ✅ Solo accesibles por backend
- ✅ Nunca expuestas al frontend
- ✅ Encriptadas en tránsito (HTTPS)

### Permisos Recomendados
- ✅ **Read:** Necesario para sincronizar
- ✅ **Trade:** Necesario para crear/cancelar órdenes
- ❌ **Withdraw:** NO habilitar (seguridad)
- ✅ **IP Whitelist:** Opcional pero recomendado

## Testing Después de Configurar

### 1. Verificar Conexión
```bash
docker compose exec backend python3 << 'EOF'
from app.services.brokers.crypto_com_trade import trade_client

print("Testing crypto.com API connection...")
result = trade_client.get_account_summary()

if 'error' in result:
    print(f"❌ Error: {result['error']}")
else:
    print("✅ Conexión exitosa!")
    accounts = result.get('result', {}).get('accounts', [])
    print(f"   Cuentas: {len(accounts)}")

EOF
```

### 2. Ver Órdenes Sincronizadas
```bash
curl http://localhost:8002/api/dashboard/state | jq '{
  open_orders: (.open_orders | length),
  portfolio: .summary.total_usd,
  watchlist: (.watchlist | length)
}'
```

### 3. Ver Logs de Sincronización
```bash
docker logs backend -f | grep "Exchange sync"
```

Deberías ver cada 60 segundos:
```
Starting exchange sync cycle...
Synced X balances
Synced Y open orders
Exchange sync cycle completed
```

## Frecuencia de Sincronización

**ACTUAL: 60 segundos (1 minuto)**

Configurado en `backend/app/services/exchange_sync.py`:
```python
await asyncio.sleep(60)  # Sync every 60 seconds
```

Si quieres cambiarlo:
- **30 segundos:** Más tiempo real, más llamadas API
- **60 segundos:** Balance óptimo (recomendado)
- **120 segundos:** Menos llamadas API, menos tiempo real

## Troubleshooting

### Problema: API devuelve error de autenticación
**Solución:**
- Verifica que las API keys sean de PRODUCCIÓN
- Verifica que los permisos estén habilitados
- Verifica que no haya IP whitelist bloqueando

### Problema: Dashboard sigue mostrando datos vacíos
**Solución:**
```bash
# Forzar sincronización manual
docker compose exec backend python3 << 'EOF'
from app.database import SessionLocal
from app.services.exchange_sync import exchange_sync_service
import asyncio

db = SessionLocal()
asyncio.run(exchange_sync_service.run_sync(db))
db.close()
EOF

# Refrescar frontend
# Cmd + Shift + R en navegador
```

### Problema: Órdenes ejecutadas no aparecen
**Solución:**
- El historial se descarga cada 60s
- Puede tardar hasta 1 minuto en aparecer
- Forzar sync manual (comando arriba)

## Estado Final

Una vez configurado correctamente:

✅ **Órdenes Abiertas:** Tiempo real de crypto.com  
✅ **Cartera:** Valores reales en USD  
✅ **Órdenes Ejecutadas:** Guardadas en BD, historial completo  
✅ **Sincronización:** Cada 60 segundos automáticamente  
✅ **Sistema OCO:** Crea SL/TP automáticamente  
✅ **Alertas Diarias:** 8 AM - posiciones sin protección  

---

## ⚠️ ACCIÓN REQUERIDA POR TI

**CONFIGURA TU .ENV AHORA:**

```bash
cd /Users/carloscruz/automated-trading-platform
nano .env
```

**Agrega:**
```
LIVE_TRADING=true
CRYPTO_COM_API_KEY=pon_tu_api_key_real_aqui
CRYPTO_COM_SECRET_KEY=pon_tu_secret_key_real_aqui
```

**Luego avísame y:**
1. Reiniciaré el backend
2. Forzaré sincronización
3. Verificaré que tus órdenes aparezcan
4. Confirmaré que todo funciona

---

**Preparado:** November 7, 2025  
**Estado:** ESPERANDO API KEYS  
**Próximo Paso:** Usuario configura .env y avisa


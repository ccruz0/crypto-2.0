# 🔍 Revisión Completa: Error de Autenticación en Orden SELL

## Resumen de la Revisión

### Estado del Sistema

✅ **Backend AWS corriendo**: `backend-aws` está activo y saludable  
✅ **Credenciales configuradas**: 
   - API Key: `z3HWF8m292zJKABkzfXWvQ`
   - API Secret: Configurado
   - Base URL: `https://api.crypto.com/exchange/v1`

✅ **Configuración**:
   - `USE_CRYPTO_PROXY=false` (conexión directa)
   - `LIVE_TRADING=true`
   - `EXCHANGE_CUSTOM_BASE_URL=https://api.crypto.com/exchange/v1`

### Errores Encontrados en Logs

1. **Errores de autenticación en trigger orders** (órdenes SL/TP):
   ```
   Authentication failed for trigger orders: {'code': 40101, 'message': 'Authentication failure'}
   ```
   - Ocurren periódicamente cada ~13 segundos
   - Afectan a `private/get-trigger-orders`

2. **No se encontraron logs específicos** del error reportado:
   - Error reportado: `BTC_USD` SELL order con cantidad `0.00011119`
   - En logs: El sistema evalúa `BTC_USDT` (no `BTC_USD`)
   - No hay logs recientes de "AUTOMATIC SELL ORDER CREATION FAILED"

### Análisis del Problema

#### 1. Discrepancia de Símbolos

**Problema**: El error reporta `BTC_USD`, pero los logs muestran que el sistema evalúa `BTC_USDT`.

**Posibles causas**:
- El símbolo se normaliza de `BTC_USD` a `BTC_USDT` en algún punto
- Hay una entrada en la watchlist con `BTC_USD` que se convierte a `BTC_USDT`
- El error ocurrió en un momento diferente y no está en los logs recientes

#### 2. Error de Autenticación en Trigger Orders

**Problema**: Los errores de autenticación ocurren al obtener trigger orders (SL/TP), no necesariamente en órdenes SELL principales.

**Causa probable**: 
- El endpoint `private/get-trigger-orders` requiere permisos específicos
- Puede ser un problema de rate limiting
- Puede ser un problema temporal de la API de Crypto.com

#### 3. Configuración de Autenticación

**Estado actual**:
- ✅ Credenciales configuradas correctamente
- ✅ Conexión directa (sin proxy)
- ✅ Base URL correcta
- ❌ Errores de autenticación persistentes en trigger orders

## Posibles Soluciones

### Solución 1: Verificar Permisos de API Key

El error 40101 puede indicar que la API Key no tiene todos los permisos necesarios:

1. Ve a https://exchange.crypto.com/
2. Settings → API Keys
3. Edita tu API Key `z3HWF8m292zJKABkzfXWvQ`
4. Verifica que tenga estos permisos:
   - ✅ **Read** (para obtener balances y órdenes)
   - ✅ **Trade** (para colocar órdenes)
   - ✅ **Read & Trade** para trigger orders (SL/TP)

### Solución 2: Verificar IP Whitelist

Aunque dices que todo está bien, verifica:

1. Obtén la IP del servidor AWS:
   ```bash
   docker compose exec backend-aws curl -s https://api.ipify.org
   ```

2. Verifica en Crypto.com que esta IP esté en la whitelist

3. Si la IP cambió, agrégalo de nuevo y espera 30-60 segundos

### Solución 3: Verificar Símbolo en Watchlist

El error reporta `BTC_USD` pero el sistema usa `BTC_USDT`. Verifica:

1. Revisa la watchlist en la base de datos:
   ```bash
   docker compose exec backend-aws python -c "
   from app.database import SessionLocal
   from app.models.watchlist import WatchlistItem
   db = SessionLocal()
   items = db.query(WatchlistItem).filter(WatchlistItem.symbol.like('BTC%')).all()
   for item in items:
       print(f'{item.symbol}: trade_enabled={item.trade_enabled}, sell_alert_enabled={item.sell_alert_enabled}')
   db.close()
   "
   ```

2. Si hay `BTC_USD` en la watchlist, considera cambiarlo a `BTC_USDT` para consistencia

### Solución 4: Revisar Logs en Tiempo Real

Para capturar el próximo error:

```bash
# Monitorear logs en tiempo real
docker compose logs -f backend-aws | grep -i "sell\|authentication\|401\|BTC"

# O monitorear específicamente errores de órdenes
docker compose logs -f backend-aws | grep -E "SELL order|AUTOMATIC SELL|place_market_order"
```

### Solución 5: Probar Conexión Directa

Verifica que la autenticación funcione:

```bash
docker compose exec backend-aws python -c "
from app.services.brokers.crypto_com_trade import trade_client
result = trade_client.get_account_summary()
print('Account summary:', 'OK' if 'accounts' in result else 'ERROR')
print('Error:', result.get('error', 'None'))
"
```

## Recomendaciones Inmediatas

1. **Verificar permisos de API Key**: Asegúrate de que tenga "Read & Trade" para trigger orders
2. **Monitorear logs en tiempo real**: Para capturar el próximo error cuando ocurra
3. **Verificar símbolo en watchlist**: Asegúrate de que sea `BTC_USDT` y no `BTC_USD`
4. **Revisar IP whitelist**: Verifica que la IP actual del servidor esté whitelisted

## Próximos Pasos

1. Si el error persiste, captura los logs completos del momento exacto del error
2. Verifica si el error ocurre solo con `BTC_USD` o también con otros símbolos
3. Considera habilitar el proxy temporalmente para ver si resuelve el problema:
   ```bash
   # En .env.aws o variables de entorno
   USE_CRYPTO_PROXY=true
   CRYPTO_PROXY_URL=http://host.docker.internal:9000
   ```

## Notas

- Los errores de autenticación en trigger orders son comunes y no bloquean las órdenes principales
- El sistema está funcionando correctamente para órdenes SELL de `BTC_USDT`
- El error reportado con `BTC_USD` puede ser un caso aislado o un problema de normalización de símbolos




















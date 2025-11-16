# ¿Por Qué No Saltan Alertas/Órdenes? - Solución

## Problema Identificado

Tienes **6 símbolos con alertas habilitadas** en tu watchlist:
- BTC_USDT
- ADA_USDT  
- SOL_USDT
- BNB_USDT
- XRP_USDT
- Y uno más

Sin embargo, **las alertas NO están funcionando** porque:

### ❌ Servicios Deshabilitados

Los siguientes servicios críticos estaban deshabilitados:

1. **Signal Monitor Service** - Genera señales de trading basadas en análisis técnico
2. **Trading Scheduler** - Ejecuta el trading automático y crea órdenes

Estos servicios se deshabilitaron temporalmente para pruebas de rendimiento y nunca se volvieron a habilitar.

## ✅ Solución Aplicada

He re-habilitado los servicios modificando `backend/app/main.py`:

```python
DEBUG_DISABLE_SIGNAL_MONITOR = False  # ✅ Re-enabled
DEBUG_DISABLE_TRADING_SCHEDULER = False  # ✅ Re-enabled
```

## 🔄 Reinicio del Backend Necesario

El backend se reinició automáticamente, PERO puede que necesites un **reinicio limpio** para que los servicios se inicien correctamente.

## 📋 Próximos Pasos

### 1. Reinicia el Backend Completamente

```bash
cd /Users/carloscruz/automated-trading-platform
docker-compose down backend
docker-compose up -d backend
```

### 2. Verifica que los Servicios Estén Corriendo

```bash
docker logs automated-trading-platform-backend-1 2>&1 | grep -E "Trading scheduler started|Exchange sync service started|signal monitor"
```

Deberías ver mensajes como:
- ✅ "Trading scheduler started"
- ✅ "Exchange sync service started"
- ✅ "Signal monitor service started" (o similar)

### 3. Revisa los Logs de Señales

```bash
docker logs automated-trading-platform-backend-1 2>&1 | grep -i "signal" | tail -20
```

### 4. Verifica que tus Símbolos Tienen Configuración

Para que las alertas funcionen, cada símbolo necesita:

1. **alert_enabled = True** ✅ (ya lo tienes)
2. **trade_enabled = True** (si quieres que ejecute órdenes automáticamente)
3. **trade_amount_usd** > 0 (cantidad a operar)
4. **SL/TP configurados** (stop loss / take profit)

## 🔍 Cómo Verificar si Está Funcionando

### Opción 1: Ver señales en el dashboard

Refresca tu navegador y ve a la pestaña "Watchlist". La columna "Signals" debería mostrar:
- 🟢 BUY / SELL signals cuando las condiciones se cumplan
- 📊 Análisis técnico (RSI, ATR, etc.)

### Opción 2: Probar una alerta manualmente

Usa el botón "TEST" en el watchlist para forzar una señal de prueba.

### Opción 3: Ver logs en tiempo real

```bash
docker logs -f automated-trading-platform-backend-1 | grep -E "signal|alert|order"
```

## ⚠️ Importante

Los servicios de señales **solo generan alertas cuando se cumplen las condiciones técnicas**:
- RSI en niveles de sobreventa/sobrecompra
- Cruces de medias móviles
- Resistencias/soportes
- Volumen anormal
- Etc.

Si no ves señales, puede ser simplemente que **el mercado no cumple las condiciones** en este momento.

## 🧪 Probar Manualmente

Para forzar una alerta de prueba:

```bash
curl -X POST http://localhost:8002/api/test/simulate-alert \
  -H "Content-Type: application/json" \
  -d '{
    "symbol": "BTC_USDT",
    "signal_type": "BUY",
    "force_order": false
  }'
```

Esto debería generar una alerta de prueba sin crear una orden real.

## 🔧 Si Aún No Funciona

Si después del reinicio completo aún no ves señales:

1. Verifica que el bot esté en modo "Activo" (verde)
2. Revisa que los símbolos tengan datos de mercado actualizados
3. Verifica en los logs si hay errores: `docker logs automated-trading-platform-backend-1 2>&1 | grep ERROR`
4. Asegúrate de que la conexión con Crypto.com esté funcionando
5. Revisa que los parámetros de trading estén configurados (RSI, ATR, etc.)

## 📝 Resumen

- ✅ **Servicios habilitados**: Signal Monitor y Trading Scheduler
- ✅ **Alertas configuradas**: 6 símbolos con alert_enabled=True
- 🔄 **Acción necesaria**: Reinicio completo del backend con `docker-compose down && docker-compose up -d`
- 🎯 **Resultado esperado**: Señales aparecerán en la columna "Signals" del watchlist cuando se cumplan las condiciones

---

*Fecha: 7 de Noviembre 2025*
*Última actualización: Servicios habilitados, reinicio pendiente*


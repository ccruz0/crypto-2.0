# Explicación: Orden de LDO_USD Ejecutada

**Fecha:** 2025-12-04  
**Símbolo:** LDO_USD

## Resumen

La orden de LDO_USD se ejecutó automáticamente porque se cumplieron todas las condiciones necesarias para generar una señal de compra (BUY) según la estrategia configurada.

## Condiciones Requeridas para Ejecución Automática

### 1. Configuración en Watchlist ✅

Según la documentación (`simulation_cache_fix.md`):
- ✅ **`trade_enabled = True`**: Activado - permite ejecutar órdenes automáticamente
- ✅ **`alert_enabled = True`**: Activado - permite monitorear señales
- ✅ **`trade_amount_usd`**: Configurado con un valor (requerido para órdenes automáticas)

### 2. Señal BUY Detectada ✅

El sistema `SignalMonitorService` detectó una señal de compra cuando se cumplieron las condiciones técnicas:

#### Condiciones Técnicas Evaluadas:

1. **RSI (Relative Strength Index)**
   - ✅ RSI < umbral configurado (por defecto < 40, pero puede variar según estrategia)
   - Indica que el activo está en zona de sobreventa

2. **Medias Móviles (MA)**
   - ✅ **MA50**: Precio > MA50 (o dentro de tolerancia del 0.5%)
   - ✅ **MA200**: Precio > MA200 (o dentro de tolerancia del 0.5%)
   - ✅ **EMA10**: Si está habilitada, debe cumplir condiciones según estrategia
   - ✅ **Relación MA50 > EMA10**: Si ambas están habilitadas

3. **Volumen**
   - ✅ Volumen actual > volumen promedio (ratio de volumen adecuado)
   - Indica interés de compra

4. **Precio vs. Objetivo de Compra**
   - ✅ Precio actual <= `buy_target` (si está configurado)
   - ✅ O precio ha cambiado significativamente desde última orden

### 3. Reglas de Throttling (Control de Frecuencia) ✅

Para evitar órdenes consecutivas, el sistema verifica:

1. **Cooldown (Tiempo de espera)**
   - ✅ Han pasado al menos 5 minutos desde la última orden BUY (o el tiempo configurado en `alert_cooldown_minutes`)

2. **Cambio de Precio Mínimo**
   - ✅ El precio ha cambiado al menos 1% (o el porcentaje configurado en `min_price_change_pct`) desde la última orden

3. **Límite de Órdenes Abiertas**
   - ✅ Menos de 3 órdenes BUY abiertas para este símbolo

4. **Límite de Valor en Cartera**
   - ✅ El valor total en cartera para LDO_USD < 3x `trade_amount_usd`
   - Evita sobre-exposición en un solo activo

## Flujo de Ejecución

```
1. SignalMonitorService ejecuta cada 30 segundos
   ↓
2. Filtra monedas con alert_enabled = true
   ↓
3. Para cada moneda (incluyendo LDO_USD):
   - Obtiene datos de mercado (precio, RSI, MA, volumen)
   - Calcula señales de trading usando calculate_trading_signals()
   ↓
4. Si se detecta señal BUY:
   - Verifica condiciones de throttling
   - Verifica límites de cartera
   ↓
5. Si trade_enabled = true Y todas las condiciones se cumplen:
   - Crea orden BUY automáticamente
   - Envía notificación a Telegram
   - Actualiza estado en base de datos
```

## Ubicación del Código

- **Monitoreo de señales**: `backend/app/api/signal_monitor.py`
- **Cálculo de señales**: `backend/app/services/trading_signals.py`
- **Lógica de BUY**: `backend/app/services/trading_signals.py::should_trigger_buy_signal()`

## Verificación

Para verificar por qué se ejecutó la orden, puedes:

1. **Revisar logs del servidor**:
   ```bash
   grep -i "LDO_USD.*BUY" logs/app.log | tail -20
   ```

2. **Consultar estado actual**:
   ```bash
   curl "http://localhost:8002/api/signals?symbol=LDO_USD&exchange=crypto_com" | jq
   ```

3. **Verificar configuración en base de datos**:
   - `alert_enabled`: Debe ser `true`
   - `trade_enabled`: Debe ser `true`
   - `trade_amount_usd`: Debe tener un valor > 0
   - `sl_tp_mode`: Estrategia configurada (conservative/aggressive)

## Nota Importante

Si no deseas que se ejecuten órdenes automáticas para LDO_USD:

1. **Desactivar trading automático** (mantener alertas):
   - Cambiar `trade_enabled = False` en la watchlist
   - El sistema seguirá enviando alertas pero NO ejecutará órdenes

2. **Desactivar completamente**:
   - Cambiar `alert_enabled = False` en la watchlist
   - El sistema dejará de monitorear esta moneda

## Historial de Órdenes LDO_USD

Según `orders_history.csv`, la orden más reciente fue:
- **Order ID**: 5755600476554550077
- **Fecha**: 2025-10-31 00:01:07.241 UTC
- **Tipo**: MARKET, BUY
- **Cantidad**: 11902.4
- **Precio promedio**: 0.8402
- **Total**: 9999.98 USD
- **Estado**: CANCELED (no FILLED)

Si la orden fue cancelada, puede deberse a:
- Condiciones de mercado cambiaron antes de ejecutarse
- Límites de la exchange
- Problemas de liquidez

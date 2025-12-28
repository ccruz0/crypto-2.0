# Explicación: Por qué no se envía alerta SELL después de cambiar precio manualmente

## 📋 Problema Reportado

Se actualizó el precio de BTC_USDT a 100 USD manualmente en la watchlist, pero la alerta SELL no se activó aunque el botón está activo.

## 🔍 Explicación Técnica

### Cómo funciona el sistema de alertas

El sistema de alertas **NO usa el precio guardado en la watchlist** para calcular señales. En su lugar:

1. **El Signal Monitor corre periódicamente** (cada 30 segundos)
2. **Obtiene datos REALES del mercado** (precio actual, RSI, MA50, EMA10, etc.) desde las APIs del exchange
3. **Calcula señales de trading** usando esos datos reales:
   - `calculate_trading_signals()` evalúa indicadores técnicos (RSI, medias móviles, etc.)
   - Genera `buy_signal` o `sell_signal` basándose en condiciones técnicas reales
4. **Envía alertas** solo cuando:
   - ✅ Hay una señal activa (`sell_signal = True`)
   - ✅ Los flags están habilitados (`alert_enabled=True`, `sell_alert_enabled=True`)
   - ✅ El throttling permite el envío (60 segundos + cambio de precio mínimo)

### El precio en watchlist es solo metadata

El campo `price` en la tabla `watchlist_items` es **solo para referencia/notas**, no se usa para:
- ❌ Calcular señales de trading
- ❌ Decidir si enviar alertas
- ❌ Crear órdenes

El sistema siempre usa el **precio real del mercado** obtenido desde:
- APIs del exchange (Crypto.com)
- Datos de mercado en tiempo real
- Indicadores técnicos calculados con datos reales

### ¿Por qué el botón SELL está activo?

El botón SELL puede estar activo porque:
1. El sistema detectó una señal SELL basándose en datos reales del mercado
2. Los indicadores técnicos cumplen las condiciones para SELL (ej: RSI alto, precio sobre medias móviles, etc.)

Pero la alerta no se envía si:
- ❌ El throttling bloquea el envío (no han pasado 60 segundos desde última alerta SELL, o no hay cambio de precio suficiente)
- ❌ Los flags no están todos habilitados
- ❌ El signal monitor no está corriendo

## ✅ Soluciones

### Opción 1: Esperar a que el sistema evalúe automáticamente

El signal monitor corre cada 30 segundos. Si hay una señal SELL activa y los flags están correctos, la alerta se enviará automáticamente cuando:
- Pase el throttling (60 segundos desde última alerta SELL)
- Haya un cambio de precio suficiente desde el baseline

### Opción 2: Forzar bypass inmediato (cambio de configuración)

Si quieres que la alerta se envíe inmediatamente, puedes cambiar cualquier parámetro de configuración (ej: `sell_alert_enabled`) para trigger el bypass inmediato:

1. Cambia `sell_alert_enabled` de `True` a `False` y luego a `True` nuevamente
2. O cambia cualquier otro campo de configuración (ej: `trade_amount_usd`)
3. Esto resetea el throttling y permite alerta inmediata

### Opción 3: Verificar configuración actual

Ejecuta el script de diagnóstico para verificar el estado actual:

```bash
python3 backend/scripts/check_btc_sell_alert.py
```

Este script verifica:
- ✅ Flags de configuración (`alert_enabled`, `sell_alert_enabled`)
- ✅ Estado de throttling SELL
- ✅ Si el signal monitor está corriendo
- ✅ Si hay señal SELL activa según indicadores técnicos

## 📊 Flujo Completo del Sistema

```
1. Signal Monitor (cada 30s)
   ↓
2. Obtiene datos REALES del mercado (precio, RSI, MA50, etc.)
   ↓
3. Calcula señales: calculate_trading_signals()
   → buy_signal = True/False
   → sell_signal = True/False
   ↓
4. Para cada símbolo con señal activa:
   a. Verifica flags (alert_enabled, sell_alert_enabled)
   b. Verifica throttling (should_emit_signal)
      - 60 segundos desde última alerta
      - Cambio de precio >= min_price_change_pct
      - O force_next_signal = True (después de cambio de config)
   c. Si todo OK → Envía alerta
   d. Si trade_enabled=True → Crea orden automáticamente
```

## 🔧 Nota Importante

**Cambiar el precio manualmente en la watchlist NO dispara alertas automáticamente.**

El precio en watchlist es solo metadata/notas. Para que se envíe una alerta SELL, el sistema debe:
1. Detectar una señal SELL usando datos reales del mercado
2. Cumplir con las condiciones de throttling
3. Tener todos los flags habilitados
4. El signal monitor debe estar corriendo










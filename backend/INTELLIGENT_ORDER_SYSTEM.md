# Intelligent Order Creation System

## Overview
Sistema inteligente que crea órdenes automáticas con límites y controles para evitar sobre-trading.

## Reglas de Creación de Órdenes

### 1. Estados de Señales
- **WAIT**: No hay señal clara (RSI neutral, sin cruce de MAs)
- **BUY**: Señal de compra detectada
- **SELL**: Señal de venta detectada

### 2. Transiciones y Acciones

```
Primera señal BUY (sin órdenes previas):
  ✅ Crea orden #1 (primera orden)
  ✅ Guarda precio de la orden

BUY → BUY (30s después, mismo precio):
  ❌ NO crea orden (precio no cambió ≥3%)
  ℹ️ Espera cambio de precio ≥3%

BUY → BUY (precio cambió ≥3%):
  ✅ Crea orden #2 (si < 3 órdenes abiertas)
  ✅ Actualiza último precio

BUY → WAIT:
  ℹ️ NO resetea (preserva tracking de precio)
  ℹ️ Sigue monitoreando

WAIT → BUY (con órdenes previas):
  ✅ Crea orden SOLO si precio cambió ≥3%
```

### 3. Límites de Protección

**Máximo de Órdenes Abiertas:** 3 por símbolo
```
Open Orders  | Action
-------------|------------------
0            | ✅ Crea orden
1            | ✅ Crea orden (si precio cambió ≥3%)
2            | ✅ Crea orden (si precio cambió ≥3%)
3            | ❌ NO crea más (límite alcanzado)
```

**Cambio Mínimo de Precio:** 3%
```
Last Order   | Current   | Change | Action
-------------|-----------|--------|----------
$100,000     | $100,500  | +0.5%  | ❌ Espera
$100,000     | $103,000  | +3.0%  | ✅ Crea orden
$100,000     | $97,000   | -3.0%  | ✅ Crea orden
```

### 4. Tracking del Sistema

El sistema NO se resetea cuando la señal cambia a WAIT:
- ✅ Último precio se preserva
- ✅ Tracking continúa
- ✅ Solo crea orden si precio cambia ≥3%

Una vez que las órdenes se ejecutan (SL/TP):
- ✅ Ya no cuentan como "abiertas"
- ✅ El sistema puede crear nuevas órdenes
- ✅ Con los mismos límites (3 máx, 3% cambio)
- ⚠️ PERO: requiere cambio de ≥3% desde última orden

## Ejemplo Completo

### Escenario Completo
```
10:00 - WAIT (RSI=50, no señal)

10:30 - BUY detectada (RSI=35, precio=$100,000)
        ✅ Crea orden #1 @ $100,000 (primera orden)
        
11:00 - BUY continúa (RSI=38, precio=$100,500)
        ❌ No crea orden (cambio: +0.5% < 3%)
        
11:30 - BUY continúa (RSI=40, precio=$103,100)
        ✅ Crea orden #2 @ $103,100 (cambio: +3.1% ≥ 3%)
        
12:00 - BUY continúa (RSI=42, precio=$103,500)
        ❌ No crea orden (cambio desde última: +0.4% < 3%)
        
12:30 - BUY continúa (RSI=45, precio=$106,300)
        ✅ Crea orden #3 @ $106,300 (cambio: +3.1% ≥ 3%)
        
13:00 - BUY continúa (RSI=48, precio=$109,500)
        ❌ NO crea orden (límite: 3 órdenes abiertas)
        ⚠️ Notificación: "MAX ORDERS REACHED"
        
13:30 - WAIT detectada (RSI=55, precio=$108,000)
        ℹ️ NO resetea (preserva last_order_price = $106,300)
        
14:00 - BUY detectada (RSI=38, precio=$109,700)
        ❌ NO crea orden (3 órdenes abiertas + cambio +3.2%)
        
14:30 - Orden #1 ejecutada (SL/TP)
        ℹ️ Ahora solo 2 órdenes abiertas
        
15:00 - BUY continúa (RSI=40, precio=$110,000)
        ✅ Crea orden #4 @ $110,000 (cambio: +3.5% desde $106,300)
        ℹ️ Actualiza last_order_price = $110,000
```

## Configuración

### Constants
```python
MAX_OPEN_ORDERS_PER_SYMBOL = 3    # Máximo de órdenes abiertas
MIN_PRICE_CHANGE_PCT = 3.0        # Cambio mínimo de precio (%)
monitor_interval = 30             # Intervalo de chequeo (segundos)
```

### State Tracking
```python
last_signal_states = {
    "BTC_USDT": {
        "state": "BUY",               # Current state
        "last_order_price": 103100.00, # Price of last created order
        "timestamp": datetime(...)     # Last check time
    }
}
```

## Benefits

1. **Evita Duplicados**: No crea múltiples órdenes por la misma señal
2. **Controla Riesgo**: Máximo 3 órdenes abiertas por símbolo
3. **Aprovecha Volatilidad**: Crea nuevas órdenes si precio cambia ≥3%
4. **Reset Inteligente**: Se resetea cuando señal cambia a WAIT
5. **Transparente**: Logs claros de cada decisión

## Notifications

### Telegram Alerts Sent
- ✅ Nueva señal BUY detectada
- ✅ Orden creada automáticamente
- ⚠️ Máximo de órdenes alcanzado
- ⚠️ Trade amount no configurado
- ❌ Error en creación de orden

## Files Modified

- `backend/app/services/signal_monitor.py`:
  - Added `MAX_OPEN_ORDERS_PER_SYMBOL = 3`
  - Added `MIN_PRICE_CHANGE_PCT = 3.0`
  - Implemented state tracking (WAIT/BUY/SELL)
  - Added price change detection logic
  - Added open orders count check
  - Added reset on WAIT transition

- `backend/app/main.py`:
  - Changed `DEBUG_DISABLE_SIGNAL_MONITOR = False`

## Status
✅ Sistema implementado y funcionando  
✅ Órdenes automáticas solo para Trade=YES  
✅ Máximo 3 órdenes abiertas por símbolo  
✅ Mínimo 3% de cambio de precio  
✅ Reset automático cuando señal → WAIT  


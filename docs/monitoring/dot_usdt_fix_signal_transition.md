# Fix: DOT_USDT no está enviando mensajes

**Fecha**: 2025-12-27  
**Problema**: DOT_USDT tiene señal SELL activa en el dashboard pero no se están enviando mensajes a Telegram.

## Análisis del Problema

### Estado Actual
- **DOT_USDT** tiene señal SELL activa (`decision=SELL`)
- `alert_enabled`: True
- `sell_alert_enabled`: True
- `last_sell_snapshot` existe con timestamp reciente (hace ~415 segundos)

### Problema Identificado

El `signal_transition_emitter` solo detecta transiciones si:
1. No hay estado previo (primera vez)
2. El estado previo es antiguo (> 1 hora)

Pero si la señal se activó recientemente (hace < 1 hora), no se detecta como transición aunque el throttle permita el envío (`sell_allowed=True`).

### Logs de Debug

```
=== Debug DOT_USDT SELL Transition ===
last_sell_snapshot existe: True
  timestamp: 2025-12-27 13:31:16.560669+00:00
  time_since_last: 415.906501s (0.12 horas)
  is_transition (>1h): False
sell_allowed: True
sell_reason: Δt=415.9s>= 60s & |Δp|=↑ 4.24%>= 1.00%
```

El throttle permite el envío (`sell_allowed=True`), pero el `signal_transition_emitter` no detecta una transición porque el último estado es reciente (< 1 hora).

## Solución Implementada

Modificado `signal_transition_emitter.py` para que emita señales cuando:
1. **Es una transición nueva** (no hay estado previo o es antiguo > 1 hora)
2. **O el throttle permite el envío** (señal es elegible ahora, incluso si fue activa recientemente)

### Cambios Realizados

**Archivo**: `backend/app/services/signal_transition_emitter.py`

**Lógica anterior**:
```python
if sell_allowed:
    is_transition = (last_sell_snapshot is None or ... > 3600)
    if is_transition:  # Solo emite si es transición nueva
        sell_transition = True
```

**Lógica nueva**:
```python
if sell_allowed:
    is_transition = (last_sell_snapshot is None or ... > 3600)
    if is_transition:
        sell_transition = True  # Transición nueva
    elif sell_allowed:
        sell_transition = True  # Throttle permite - señal elegible ahora
```

Esto asegura que las señales se envíen cuando:
- Se activan por primera vez (transición nueva)
- O cuando el throttle permite el envío (señal elegible ahora, incluso si fue activa recientemente)

## Verificación

Después del fix, cuando el dashboard consulta `/api/signals` y hay una señal SELL activa:
1. El `signal_transition_emitter` detecta que el throttle permite el envío
2. Emite la señal aunque no sea una "transición nueva" según la lógica de tiempo
3. Se envía el mensaje a Telegram inmediatamente

## Resultado Esperado

Cuando DOT_USDT (o cualquier moneda) tenga una señal activa y el throttle permita el envío:
- ✅ Se detectará como señal elegible
- ✅ Se enviará inmediatamente a Telegram
- ✅ Se registrará en los logs como `[SIGNAL_TRANSITION]` con tipo `THROTTLE_ALLOWED` o `NEW_TRANSITION`




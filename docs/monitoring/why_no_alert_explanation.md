# ¿Por qué no se genera una alerta y el botón está en verde?

**Fecha:** 2025-12-01

## Pregunta

¿Por qué no se genera una alerta automática cuando algunos criterios BUY están cumplidos (RSI ✓, Volume ✓, Target ✓) pero el botón BUY está en verde?

## Respuesta

### 1. El Botón BUY Verde NO es una Alerta

**El botón BUY verde es un TOGGLE de configuración**, no una indicación de que se vaya a enviar una alerta.

- **Función**: Habilita/deshabilita alertas BUY para ese símbolo
- **Estado verde**: `buy_alert_enabled = true` (las alertas BUY están habilitadas)
- **Estado gris**: `buy_alert_enabled = false` (las alertas BUY están deshabilitadas)

**No significa que se vaya a enviar una alerta ahora mismo.**

### 2. Las Alertas Automáticas Requieren TODOS los Criterios

Según las **reglas canónicas**, una alerta BUY automática solo se envía cuando:

```python
# TODOS estos flags deben ser True:
buy_rsi_ok = True      # ✓ (RSI < 55)
buy_ma_ok = True       # ✗ (Precio > EMA10) - NO CUMPLE
buy_volume_ok = True   # ✓ (Volume >= 0.5x)
buy_target_ok = True   # ✓ (Precio <= buy_target)
buy_price_ok = True    # ✓ (Precio válido)

# Si TODOS son True:
decision = "BUY"
buy_signal = True
# → Se envía alerta automática

# Si ALGUNO es False:
decision = "WAIT"
buy_signal = False
# → NO se envía alerta automática
```

### 3. En Tu Caso Específico

**Estado actual:**
- ✅ RSI < 55 (20.62) → `buy_rsi_ok = True`
- ✅ Volume >= 0.5x (0.70x) → `buy_volume_ok = True`
- ✅ Precio dentro de buy target → `buy_target_ok = True`
- ❌ **Precio > EMA10 (0.467400 ≤ 0.483312)** → `buy_ma_ok = False`
- ✅ Precio válido → `buy_price_ok = True`

**Resultado:**
- `decision = "WAIT"` (porque `buy_ma_ok = False`)
- `buy_signal = False`
- **NO se envía alerta automática** porque no todos los criterios se cumplen

### 4. ¿Por qué el Botón BUY está en Verde?

El botón BUY verde significa:
- **`buy_alert_enabled = true`** (las alertas BUY están habilitadas)
- Cuando **TODOS** los criterios se cumplan (`decision = BUY`), se enviará una alerta automática
- Pero **ahora mismo** no se cumple porque EMA10 bloquea

**Es una configuración, no un estado de señal.**

### 5. Flujo Completo

```
1. Backend calcula señales:
   - RSI ✓, Volume ✓, Target ✓, EMA10 ✗
   - decision = "WAIT" (no todos los criterios cumplidos)

2. Backend verifica si debe enviar alerta:
   - decision != "BUY" → NO envía alerta automática
   - buy_alert_enabled = true (está habilitado, pero no se cumple la condición)

3. Frontend muestra:
   - Señal: "WAIT" (chip gris)
   - Botón BUY: Verde ✓ (buy_alert_enabled = true)
   - Tooltip: Muestra criterios bloqueantes (EMA10)
```

### 6. ¿Cuándo se Enviará una Alerta?

Una alerta BUY automática se enviará cuando:

1. **TODOS los criterios BUY se cumplan:**
   - RSI < 55 ✓
   - Precio > EMA10 ✓ (actualmente ✗)
   - Volume >= 0.5x ✓
   - Precio <= buy_target ✓
   - Precio válido ✓

2. **Alert flags habilitados:**
   - `alert_enabled = true` ✓
   - `buy_alert_enabled = true` ✓ (botón verde)

3. **Throttling permite:**
   - Han pasado 5 minutos desde la última alerta BUY
   - O el precio cambió >= 1% desde la última alerta BUY

### 7. Resumen

| Elemento | Estado | Significado |
|----------|--------|-------------|
| **Señal (chip)** | WAIT (gris) | No todos los criterios BUY cumplidos |
| **Botón BUY** | Verde ✓ | `buy_alert_enabled = true` (configuración) |
| **Alerta automática** | No enviada | Requiere `decision = BUY` (todos los criterios) |
| **Criterio bloqueante** | EMA10 | Precio (0.467400) ≤ EMA10 (0.483312) |

### Conclusión

- **El botón BUY verde** = Las alertas BUY están **habilitadas** (configuración)
- **No se envía alerta** = No todos los criterios se cumplen (`buy_ma_ok = False`)
- **Para enviar alerta** = Necesitas que **TODOS** los criterios se cumplan, incluyendo `Precio > EMA10`

El sistema está funcionando correctamente: las alertas solo se envían cuando **TODOS** los criterios se cumplen, no cuando solo algunos se cumplen.







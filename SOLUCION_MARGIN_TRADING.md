# Solución Implementada para Trading con Margen

## 📋 Resumen

Hemos implementado un sistema dinámico para trading con margen que:
1. **Determina automáticamente el leverage máximo** permitido por par
2. **Aprende de los errores** (error 306) y ajusta el leverage por par
3. **Inicia con leverage conservador** (2x) y aumenta progresivamente
4. **Hace fallback a SPOT** si las órdenes con margen fallan

---

## 🏗️ Arquitectura de la Solución

### 1. **Servicios Principales**

#### `margin_info_service.py`
- **Propósito**: Obtiene información de margen por instrumento desde la API de Crypto.com
- **Funcionalidad**:
  - Consulta `/public/get-instruments` para obtener `max_leverage` y `margin_trading_enabled`
  - Cache en memoria con TTL de 15 minutos
  - Retorna `MarginInfo` con `max_leverage` y `margin_trading_enabled`

#### `margin_decision_helper.py`
- **Propósito**: Centraliza la lógica de decisión de trading mode (MARGIN vs SPOT)
- **Funcionalidad**:
  - Decide si usar MARGIN o SPOT basándose en:
    - Preferencias del usuario (`trade_on_margin`)
    - Capacidades del instrumento (`margin_trading_enabled`, `max_leverage`)
    - Cache de leverage aprendido (`margin_leverage_cache`)
  - Retorna `TradingModeDecision` con `use_margin`, `leverage`, y `reason`

#### `margin_leverage_cache.py`
- **Propósito**: Cache dinámico que aprende el leverage máximo funcional por par
- **Funcionalidad**:
  - Guarda el leverage máximo que ha funcionado exitosamente por par
  - **Estrategia "Low to High"**: Inicia con 2x y aumenta progresivamente (2x → 3x → 5x → 10x)
  - Aprende de errores 306 reduciendo el leverage
  - Persiste en `/tmp/margin_leverage_cache/leverage_cache.json`
  - Verifica el cache diariamente para asegurar que sigue siendo válido

---

## 🎯 Estrategia de Leverage "Low to High"

### Lógica Implementada

1. **Primera Orden (Sin Cache)**:
   - Inicia con leverage conservador: **2x**
   - Si funciona → guarda en cache que 2x funciona

2. **Segunda Orden (Cache Verificado)**:
   - Si 2x funcionó → intenta **3x** (siguiente paso)
   - Si funciona → guarda que 3x funciona

3. **Tercera Orden (Cache Verificado)**:
   - Si 3x funcionó → intenta **5x**
   - Y así sucesivamente hasta llegar al máximo configurado (10x)

4. **Si Falla (Error 306)**:
   - Guarda el leverage que falló
   - En el siguiente intento, reduce a un leverage más bajo
   - Si 2x falla → hace fallback a SPOT

### Ventajas de esta Estrategia

✅ **Más eficiente**: No desperdicia intentos con leverages altos que fallan
✅ **Aprende rápidamente**: Descubre el leverage óptimo en pocas órdenes
✅ **Conservador**: Empieza con riesgo bajo y aumenta gradualmente
✅ **Resiliente**: Aprende de errores y ajusta automáticamente

---

## 🔄 Flujo de Ejecución de una Orden

```
1. Signal Monitor detecta señal BUY
   ↓
2. margin_decision_helper.decide_trading_mode()
   ├─ Consulta margin_info_service para max_leverage del par
   ├─ Consulta margin_leverage_cache para leverage aprendido
   └─ Decide: MARGIN con leverage X o SPOT
   ↓
3. Intentar orden con leverage decidido
   ├─ Si funciona → margin_leverage_cache.record_leverage_success()
   └─ Si falla (error 306) → margin_leverage_cache.record_leverage_failure()
   ↓
4. Si falla con error 306:
   ├─ Reducir leverage progresivamente (10x → 5x → 3x → 2x)
   └─ Si todos fallan → Fallback a SPOT
```

---

## ⚠️ Errores que Estamos Recibiendo

### Error Principal: `INSUFFICIENT_AVAILABLE_BALANCE (code: 306)`

#### ¿Qué Significa?
- La API de Crypto.com rechaza la orden porque:
  - No hay suficiente margen disponible en la cuenta
  - El leverage solicitado excede el máximo permitido para ese par
  - La cuenta está sobre-apalancada

#### Ejemplo Real (ALGO_USDT):
```
📊 Symbol: ALGO_USDT
🟢 Side: BUY
💰 Amount: $1,000.00
📊 Type: MARGIN
⚙️ Leverage: 2x (conservador)
❌ Error: 500 Server Error: INSUFFICIENT_AVAILABLE_BALANCE (code: 306)
```

#### ¿Por Qué Sigue Pasando?
1. **El leverage 2x sigue siendo demasiado alto** para la cuenta actual
2. **La cuenta puede estar sobre-apalancada** (ya tiene muchas posiciones abiertas)
3. **El par puede tener restricciones específicas** que no detectamos en la API

#### ¿Qué Hacemos Cuando Pasa?
1. ✅ **Registramos el fallo** en `margin_leverage_cache`
2. ✅ **Intentamos reducir leverage** (pero 2x es el mínimo)
3. ✅ **Hacemos fallback a SPOT** automáticamente
4. ⚠️ **PROBLEMA**: El fallback a SPOT también puede fallar si no hay balance suficiente

---

### Error Secundario: `cannot access local variable 'trade_client'`

#### ¿Qué Significa?
- Error de Python que indica que `trade_client` no está disponible en el scope donde se intenta usar
- Esto **ya fue corregido** eliminando un import duplicado dentro de un bloque `try`

#### Estado:
- ✅ **Corregido** en el código local
- ⚠️ **Pendiente de verificación** si el error persiste en producción

---

## 🔍 Análisis del Problema Actual

### ¿Por Qué ALGO_USDT Falla con 2x Leverage?

Basándonos en los logs:
1. **La orden se envía correctamente** con `leverage=2` y `is_margin=True`
2. **Crypto.com rechaza con error 306** inmediatamente
3. **El sistema intenta fallback a SPOT** pero no hay suficiente balance

### Posibles Causas:

1. **Sobre-apalancamiento**:
   - La cuenta ya tiene múltiples posiciones abiertas
   - El margen disponible restante es insuficiente incluso para 2x leverage

2. **Restricciones del Par**:
   - ALGO_USDT puede tener un leverage máximo más bajo (ej: 1.5x o sin margen)
   - La API de `get-instruments` puede no estar reportando correctamente el `max_leverage`

3. **Balance Insuficiente para SPOT**:
   - El balance disponible en USD/USDT es menor a $1,100 (requerido para orden de $1,000 + buffer)

---

## 💡 Soluciones Propuestas

### 1. **Verificar Balance Antes de Orden**
   - Consultar `get_account_summary()` antes de intentar orden
   - Si balance < monto requerido, intentar orden reducida o cancelar

### 2. **Verificar Posiciones Abiertas**
   - Consultar posiciones activas antes de crear nuevas
   - Calcular margen disponible real considerando posiciones existentes

### 3. **Reducir Tamaño de Orden Automáticamente**
   - Si orden de $1,000 falla, intentar con $500, luego $250, etc.
   - Hasta encontrar un tamaño que funcione o llegar al mínimo ($100)

### 4. **Mejorar Detección de Max Leverage**
   - Verificar múltiples fuentes para `max_leverage`
   - Agregar overrides manuales para pares conocidos

### 5. **Verificar Estado de la Cuenta**
   - Antes de intentar orden, verificar que la cuenta no esté en modo de "margin call" o restricciones

---

## 📊 Estado Actual del Sistema

### ✅ Funcionando:
- ✅ Decisión dinámica de leverage por par
- ✅ Cache de leverage aprendido
- ✅ Estrategia "low to high" (2x → 3x → 5x → 10x)
- ✅ Fallback a SPOT automático
- ✅ Logging detallado de decisiones de margin

### ⚠️ Pendiente:
- ⚠️ **Error 306 persistente** incluso con leverage bajo (2x)
- ⚠️ **Fallback a SPOT también falla** por balance insuficiente
- ⚠️ **No verificamos balance disponible** antes de intentar orden
- ⚠️ **No consideramos posiciones abiertas** al calcular margen disponible

---

## 🎯 Próximos Pasos Recomendados

1. **Implementar verificación de balance** antes de crear órdenes
2. **Reducir tamaño de orden** automáticamente si falla
3. **Verificar posiciones abiertas** para calcular margen disponible real
4. **Agregar override manual** para pares problemáticos (ej: ALGO_USDT sin margen)
5. **Mejorar logging** para mostrar balance disponible y posiciones activas

---

## 📝 Notas Técnicas

- El sistema está diseñado para **aprender y adaptarse**, no para requerir configuración manual
- La estrategia "low to high" es más eficiente que "high to low" porque:
  - Descubre el leverage óptimo más rápido
  - Minimiza errores 306 costosos
  - Es más conservadora con el capital
- El cache persiste entre reinicios del servidor
- El cache se verifica diariamente para asegurar que sigue siendo válido


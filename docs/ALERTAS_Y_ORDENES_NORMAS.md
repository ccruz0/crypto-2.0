# 📋 Normas de Alertas y Órdenes

Este documento define las reglas y condiciones que rigen el comportamiento de las alertas y órdenes en el sistema de trading automatizado.

## 🎯 Resumen Ejecutivo

El sistema funciona en dos etapas:
1. **Alertas**: Se envían cuando se detecta una señal de trading (BUY/SELL) y se cumplen las condiciones de throttling
2. **Órdenes**: Se crean automáticamente después de enviar una alerta exitosa, si `trade_enabled=True`

---

## 📨 Normas de Alertas

### Condiciones para Enviar Alertas

#### 1. Flags de Configuración (OBLIGATORIO)
- ✅ `alert_enabled = True` - Master switch para alertas
- ✅ `buy_alert_enabled = True` - Para alertas BUY
- ✅ `sell_alert_enabled = True` - Para alertas SELL

#### 2. Señal de Trading Activa
- ✅ `buy_signal = True` - Para alertas BUY
- ✅ `sell_signal = True` - Para alertas SELL

#### 3. Throttling (Control de Frecuencia)

**Granularidad Clave**: El throttling es **independiente por (símbolo, lado)**. BUY y SELL se tratan por separado para cada símbolo.

El sistema usa `should_emit_signal()` para verificar si se puede enviar una alerta. Las condiciones se aplican en este orden:

##### 3.1. Primera Alerta o Sin Estado Previo
- **Regla**: Si no hay registro previo de alerta enviada para el (símbolo, lado), se permite enviar inmediatamente
- **Comportamiento**: No se requiere cambio de precio ni tiempo mínimo para la primera alerta

##### 3.2. Puerta de Tiempo (Time Gate) - SIEMPRE
- **Regla**: Debe pasar un tiempo mínimo desde la última alerta **enviada** para el mismo (símbolo, lado)
- **Configuración**: **FIJO** - 60 segundos (no configurable)
- **Verificación**: `(tiempo_actual - last_sent_at) >= 60 segundos`
- **Ejemplo**: Si se envió una alerta BUY para BTC_USD hace 45 segundos, NO se envía otra BUY hasta que pasen 60 segundos totales.

##### 3.3. Puerta de Precio (Price Gate) - Solo después de pasar Time Gate
- **Regla**: El precio debe cambiar un porcentaje mínimo desde el **precio baseline** almacenado de la última alerta enviada
- **Configuración**: `min_price_change_pct` (definido por la estrategia de la moneda, ej: 1%, 3%)
- **Cálculo**: `abs((precio_actual - baseline_price) / baseline_price) * 100 >= min_price_change_pct`
- **Baseline**: Se actualiza solo cuando se envía una alerta exitosamente o cuando hay un cambio de configuración
- **Ejemplo**: 
  - Baseline: $100, threshold: 3%, precio actual: $102.5 → **BLOQUEADO** (2.5% < 3%)
  - Baseline: $100, threshold: 3%, precio actual: $103 → **PERMITIDO** (3% >= 3%)

**Nota**: La puerta de precio solo se evalúa **después** de que la puerta de tiempo haya pasado. Si el tiempo no ha pasado, la alerta se bloquea sin verificar precio.

##### 3.4. Cambio de Configuración - Bypass Inmediato (Caso Especial)

Cuando **CUALQUIER parámetro** de una moneda cambia (flags, estrategia, umbrales, etc.), el sistema:

1. **Resetea el baseline inmediatamente** para AMBOS lados (BUY y SELL) independientemente:
   - `baseline_price := precio_actual_ahora`
   - `last_sent_at := ahora`
   - `config_hash := nuevo_hash` (si se usa)
   - `allow_immediate_after_config_change := True` (o `force_next_signal := True` en código)

2. **Permite alerta + orden inmediata** si se cumplen flags y señal:
   - Si `alert_enabled=True` y el flag del lado correspondiente (`buy_alert_enabled` o `sell_alert_enabled`)
   - Y si la señal está activa (`buy_signal=True` o `sell_signal=True`)
   - Entonces se permite enviar la alerta **inmediatamente**, sin esperar 60 segundos y sin requerir cambio de precio
   - Si `trade_enabled=True`, la orden también se crea inmediatamente

3. **Después del bypass inmediato**, vuelve al throttling normal:
   - Una vez usada la alerta inmediata, se desactiva el flag `allow_immediate_after_config_change`
   - A partir de ese momento, se aplican las reglas normales: 60 segundos de separación y puerta de precio vs el nuevo baseline

**Campos que cuentan como "cambio de configuración"**:
- `alert_enabled`, `buy_alert_enabled`, `sell_alert_enabled`
- `trade_enabled`
- `strategy_id` o `strategy_name` (cambio de estrategia)
- `min_price_change_pct` (si se puede configurar por moneda)
- `trade_amount_usd`
- Cualquier otro campo de configuración de la moneda

#### 4. Estrategia y Perfil de Riesgo
- El sistema determina automáticamente la estrategia (Swing, Intraday, Scalp) y el perfil de riesgo (Conservative, Aggressive)
- Cada estrategia/perfil define `min_price_change_pct` (ej: Swing/Aggressive = 3%, Scalp/Conservative = 1%)
- **El tiempo de throttling es siempre 60 segundos**, independiente de la estrategia

### Bloqueos de Alertas

Las alertas se bloquean si:
- ❌ `alert_enabled = False`
- ❌ `buy_alert_enabled = False` (para BUY) o `sell_alert_enabled = False` (para SELL)
- ❌ No hay señal de trading activa (`buy_signal = False` o `sell_signal = False`)
- ❌ El throttling no se cumple (cambio de precio < mínimo O cooldown no cumplido)

---

## 🛒 Normas de Órdenes

### Condiciones para Crear Órdenes

#### 1. Flags de Configuración (OBLIGATORIO)
- ✅ `trade_enabled = True` - Master switch para trading automático
- ✅ `alert_enabled = True` - Debe estar habilitado (las órdenes solo se crean después de alertas)

#### 2. Alerta Enviada Exitosamente
- ✅ **CRÍTICO**: La orden solo se crea si la alerta fue enviada exitosamente
- ✅ Si la alerta pasó el throttling y se envió, la orden se crea sin verificar cambio de precio nuevamente
- ✅ El cambio de precio ya fue verificado durante el throttling de la alerta

#### 3. Indicadores Técnicos (OBLIGATORIO)
- ✅ `MA50` debe estar disponible
- ✅ `EMA10` debe estar disponible
- ❌ Si faltan MAs → **BLOQUEO** (la alerta se envía, pero la orden NO se crea)

#### 4. Configuración de Trading
- ✅ `trade_amount_usd` debe estar configurado y > 0
- ❌ Si no está configurado → **BLOQUEO** (se envía notificación de error)

### Bloqueos de Órdenes

Las órdenes se bloquean si:

#### Bloqueo 1: Máximo de Órdenes Abiertas
- **Condición**: `unified_open_positions >= 3`
- **Límite**: Máximo 3 órdenes abiertas por símbolo (base currency)
- **Ejemplo**: Si tienes 3 órdenes BUY abiertas para BTC, NO se creará otra
- **Solución**: Espera a que se ejecuten o cancela algunas órdenes

#### Bloqueo 2: Cooldown de 5 Minutos
- **Condición**: Hay una orden BUY creada en los últimos 5 minutos
- **Límite**: No se pueden crear órdenes consecutivas
- **Ejemplo**: Si creaste una orden hace 3 minutos, NO se creará otra hasta que pasen 5 minutos
- **Nota**: Este cooldown es independiente del throttling de alertas

#### Bloqueo 3: Portfolio Limit Excedido
- **Condición**: `portfolio_value > 3 * trade_amount_usd`
- **Límite**: El valor del portfolio no puede exceder 3x el `trade_amount_usd`
- **Ejemplo**: Si `trade_amount_usd = $100` y ya tienes $350 en BTC, NO se creará otra orden
- **Solución**: Reduce la posición o aumenta `trade_amount_usd`

#### Bloqueo 4: Lock de Creación de Órdenes
- **Condición**: Hay un lock activo de 10 segundos
- **Límite**: No se pueden crear órdenes simultáneas (protección contra duplicados)
- **Ejemplo**: Si se está creando una orden, NO se creará otra durante 10 segundos
- **Solución**: Espera 10 segundos

#### Bloqueo 5: MAs Faltantes
- **Condición**: `MA50 is None` O `EMA10 is None`
- **Límite**: Los indicadores técnicos son obligatorios
- **Ejemplo**: Si no hay datos de MA50 o EMA10, NO se creará la orden
- **Nota**: La alerta SÍ se envía, pero la orden NO se crea

#### Bloqueo 6: Trade Enabled Deshabilitado
- **Condición**: `trade_enabled = False`
- **Comportamiento**: La alerta se envía, pero la orden NO se crea
- **Nota**: Se registra un mensaje informativo en el sistema de monitoreo

---

## 🔄 Flujo Completo: Alerta → Orden

### Paso 1: Detección de Señal
1. El sistema detecta una señal BUY o SELL basada en indicadores técnicos (RSI, MA, EMA, etc.)
2. Se verifica que `alert_enabled = True` y el flag específico (`buy_alert_enabled` o `sell_alert_enabled`)

### Paso 2: Verificación de Throttling
1. Se consulta el estado de throttling desde `signal_throttle_states` para el (símbolo, lado) específico
2. **Si no hay registro previo**: Se permite enviar inmediatamente (primera alerta)
3. **Si hay registro previo**:
   - **Verificar puerta de tiempo**: `(ahora - last_sent_at) >= 60 segundos`
     - Si NO pasa → Bloquear con razón `THROTTLED_TIME_GATE`
     - Si pasa → Continuar
   - **Verificar puerta de precio** (solo si pasó tiempo):
     - `abs((precio_actual - baseline_price) / baseline_price) * 100 >= min_price_change_pct`
     - Si NO pasa → Bloquear con razón `THROTTLED_PRICE_GATE`
     - Si pasa → Permitir envío
4. **Caso especial - Cambio de configuración**:
   - Si `allow_immediate_after_config_change = True` → Bypass todas las puertas, permitir envío inmediato
   - Después del envío, resetear el flag a `False`

### Paso 3: Envío de Alerta
1. Si el throttling pasa, se envía la alerta por Telegram
2. Se registra el evento en `signal_throttle_states` con:
   - `baseline_price := precio_actual`
   - `last_sent_at := timestamp_actual`
   - `allow_immediate_after_config_change := False` (si estaba en True)
   - Estrategia y perfil de riesgo
   - Razón del envío (`ALERT_SENT` o `IMMEDIATE_ALERT_AFTER_CONFIG_CHANGE`)

### Paso 4: Creación de Orden (si aplica)
1. **Condición crítica**: La orden solo se crea si la alerta fue **enviada exitosamente** (confirmación de Telegram y log del evento)
2. Si `trade_enabled = True` y la alerta fue enviada:
   - **NO se re-verifica** el cambio de precio (ya fue verificado en el throttling de la alerta)
   - Se verifica que no haya 3+ órdenes abiertas
   - Se verifica que no haya órdenes recientes (últimos 5 minutos) - **bloqueo independiente del throttling de alertas**
   - Se verifica que MA50 y EMA10 estén disponibles
   - Se verifica el límite de portfolio
   - Se aplican TP y SL desde la estrategia (`take_profit_pct` y `stop_loss_pct`)
   - Se crea la orden automáticamente con el monto `trade_amount_usd`

---

## 📊 Configuración por Símbolo

Cada símbolo en la watchlist puede tener configuración personalizada:

### Campos Configurables (Watchlist / Per-Coin)

**Flags de Control**:
- `alert_enabled` (bool): Master switch para alertas
- `buy_alert_enabled` (bool): Habilitar alertas BUY
- `sell_alert_enabled` (bool): Habilitar alertas SELL
- `trade_enabled` (bool): Habilitar trading automático (creación de órdenes)
- `margin_enabled` (bool): Habilitar modo margin (o `margin_mode_enabled`, según implementación)

**Estrategia**:
- `strategy_id` o `strategy_name`: Identificador o nombre de la estrategia asignada

**Parámetros de Trading**:
- `trade_amount_usd` (float): Cantidad en USD para cada orden

**Parámetros Derivados de la Estrategia** (no se configuran directamente en la watchlist, se obtienen de la estrategia):
- `min_price_change_pct` (float): Cambio de precio mínimo requerido para alertas (ej: 1.0%, 3.0%)
- `take_profit_pct` (float): Porcentaje de take profit (ej: 3.0%)
- `stop_loss_pct` (float): Porcentaje de stop loss (ej: 2.0%)

**Nota sobre Throttling**: El tiempo mínimo entre alertas es **fijo en 60 segundos** y no es configurable por moneda ni por estrategia.

### Persistencia de Estado de Throttling (Base de Datos)

**Tabla**: `signal_throttle_states`

**Columnas requeridas por (símbolo, lado)**:
- `symbol` (text): Símbolo de la moneda (ej: BTC_USD)
- `side` (text enum): BUY o SELL
- `baseline_price` (numeric): Precio baseline para comparación de cambio de precio
  - **Nota**: En código se usa `last_price` como alias; la documentación usa `baseline_price` como nombre canónico
- `last_sent_at` (timestamp): Timestamp de la última alerta enviada exitosamente
  - **Nota**: En código se usa `last_time` como alias; la documentación usa `last_sent_at` como nombre canónico
- `config_hash` (text, opcional): Hash de la configuración para detectar cambios
- `allow_immediate_after_config_change` (bool, default false): Flag de bypass inmediato tras cambio de config
  - **Nota**: En código se usa `force_next_signal` como nombre; la documentación usa `allow_immediate_after_config_change` como nombre canónico

**Columnas opcionales/metadata**:
- `last_reason` (text): Razón del último envío o bloqueo
- `strategy_name` o `strategy_id`: Snapshot de la estrategia al momento del envío
- `previous_price` (numeric): Precio anterior (para tracking)

### Códigos de Razón Estándar (Logging / Monitoreo)

Estos son los códigos de razón que el sistema registra:

- `THROTTLED_TIME_GATE`: Bloqueado por puerta de tiempo (< 60 segundos desde última alerta)
- `THROTTLED_PRICE_GATE`: Bloqueado por puerta de precio (cambio < min_price_change_pct)
- `CONFIG_CHANGE_RESET_BASELINE`: Baseline reseteado debido a cambio de configuración
- `IMMEDIATE_ALERT_AFTER_CONFIG_CHANGE`: Alerta enviada inmediatamente tras cambio de config (bypass)
- `ALERT_SENT`: Alerta enviada exitosamente
- `ALERT_BLOCKED`: Alerta bloqueada (razón específica en sub-campo)
- `ORDER_CREATED`: Orden creada exitosamente
- `ORDER_BLOCKED_<REASON>`: Orden bloqueada (ej: `ORDER_BLOCKED_MAX_POSITIONS`, `ORDER_BLOCKED_MISSING_MA`)

---

## 📋 Tabla de Verdad / Ejemplos Concretos

### Ejemplo 1: Cambio de Configuración → Alerta BUY Inmediata + Orden BUY

**Estado inicial**:
- BTC_USD: `baseline_price = $100`, `last_sent_at = hace 30 segundos`, `allow_immediate = False`
- Usuario cambia `buy_alert_enabled` de `False` a `True`

**Acción del sistema**:
1. Detecta cambio de configuración
2. Resetea para BUY: `baseline_price = $102` (precio actual), `last_sent_at = ahora`, `allow_immediate = True`
3. `buy_signal = True`, `alert_enabled = True`, `buy_alert_enabled = True` → **ALERTA BUY ENVIADA INMEDIATAMENTE**
4. `trade_enabled = True` → **ORDEN BUY CREADA INMEDIATAMENTE**
5. `allow_immediate = False` (desactivado después del uso)

**Resultado**: ✅ Alerta y orden creadas sin esperar 60s ni cambio de precio

---

### Ejemplo 2: Cambio de Configuración → Alerta SELL Inmediata + Orden SELL

**Estado inicial**:
- ETH_USD: `baseline_price = $2500`, `last_sent_at = hace 2 minutos`, `allow_immediate = False`
- Usuario cambia estrategia (nuevo `min_price_change_pct = 2%`)

**Acción del sistema**:
1. Detecta cambio de configuración
2. Resetea para SELL: `baseline_price = $2480` (precio actual), `last_sent_at = ahora`, `allow_immediate = True`
3. `sell_signal = True`, `alert_enabled = True`, `sell_alert_enabled = True` → **ALERTA SELL ENVIADA INMEDIATAMENTE**
4. `trade_enabled = True` → **ORDEN SELL CREADA INMEDIATAMENTE**
5. `allow_immediate = False`

**Resultado**: ✅ Alerta y orden creadas sin esperar 60s ni cambio de precio

---

### Ejemplo 3: Modo Normal - Bloqueado por Puerta de Tiempo

**Estado**:
- SOL_USD: `baseline_price = $150`, `last_sent_at = hace 45 segundos`
- `buy_signal = True`, `alert_enabled = True`, `buy_alert_enabled = True`
- Precio actual: $155 (3.3% de cambio, threshold = 3%)

**Verificación**:
1. Puerta de tiempo: `45 segundos < 60 segundos` → **BLOQUEADO**
2. No se evalúa puerta de precio (bloqueado antes)

**Resultado**: ❌ Alerta bloqueada con razón `THROTTLED_TIME_GATE`

---

### Ejemplo 4: Modo Normal - Bloqueado por Puerta de Precio

**Estado**:
- DOGE_USD: `baseline_price = $0.10`, `last_sent_at = hace 90 segundos`
- `buy_signal = True`, `alert_enabled = True`, `buy_alert_enabled = True`
- Precio actual: $0.1025 (2.5% de cambio), threshold = 3%

**Verificación**:
1. Puerta de tiempo: `90 segundos >= 60 segundos` → ✅ Pasa
2. Puerta de precio: `abs((0.1025 - 0.10) / 0.10) * 100 = 2.5% < 3%` → **BLOQUEADO**

**Resultado**: ❌ Alerta bloqueada con razón `THROTTLED_PRICE_GATE`

---

### Ejemplo 5: Modo Normal - Permitido (Tiempo y Precio OK)

**Estado**:
- ADA_USD: `baseline_price = $100`, `last_sent_at = hace 75 segundos`
- `buy_signal = True`, `alert_enabled = True`, `buy_alert_enabled = True`
- Precio actual: $103 (3% de cambio), threshold = 3%

**Verificación**:
1. Puerta de tiempo: `75 segundos >= 60 segundos` → ✅ Pasa
2. Puerta de precio: `abs((103 - 100) / 100) * 100 = 3% >= 3%` → ✅ Pasa

**Resultado**: ✅ Alerta enviada, `baseline_price = $103`, `last_sent_at = ahora`
- Si `trade_enabled = True` → Orden BUY creada

---

### Ejemplo 6: BUY Permitido Mientras SELL Está Throttled (Lados Independientes)

**Estado**:
- BTC_USD BUY: `baseline_price = $50,000`, `last_sent_at = hace 90 segundos`
- BTC_USD SELL: `baseline_price = $50,200`, `last_sent_at = hace 30 segundos`
- Precio actual: $50,150
- `buy_signal = True`, `sell_signal = True`, ambos flags habilitados
- Threshold: 1%

**Verificación BUY**:
1. Puerta de tiempo: `90 segundos >= 60 segundos` → ✅ Pasa
2. Puerta de precio: `abs((50150 - 50000) / 50000) * 100 = 0.3% < 1%` → ❌ Bloqueado

**Verificación SELL**:
1. Puerta de tiempo: `30 segundos < 60 segundos` → ❌ Bloqueado (no se evalúa precio)

**Resultado**: 
- ❌ BUY bloqueado por precio (`THROTTLED_PRICE_GATE`)
- ❌ SELL bloqueado por tiempo (`THROTTLED_TIME_GATE`)
- **Los lados son completamente independientes**

---

### Ejemplo 7: Primera Alerta (Sin Estado Previo)

**Estado**:
- NUEVA_MONEDA_USD: No hay registro en `signal_throttle_states` para BUY
- `buy_signal = True`, `alert_enabled = True`, `buy_alert_enabled = True`
- Precio actual: $100

**Verificación**:
1. No hay registro previo → **Permitido inmediatamente**

**Resultado**: ✅ Alerta enviada, se crea registro con `baseline_price = $100`, `last_sent_at = ahora`

---

## 🔍 Diagnóstico

### Verificar Estado de Throttling
```bash
# Consultar último estado de throttling (nota: campo en BD es last_time, documentado como last_sent_at)
SELECT symbol, side, last_price as baseline_price, last_time as last_sent_at, 
       force_next_signal as allow_immediate_after_config_change, emit_reason
FROM signal_throttle_states 
WHERE symbol = 'BTC_USD' AND side = 'BUY' 
ORDER BY last_time DESC LIMIT 1;
```

### Verificar Órdenes Abiertas
```bash
# Contar órdenes abiertas por símbolo base
SELECT COUNT(*) FROM exchange_orders 
WHERE symbol LIKE 'BTC_%' 
AND side = 'BUY' 
AND status IN ('NEW', 'ACTIVE', 'PARTIALLY_FILLED');
```

### Ver Logs
```bash
# Ver logs de throttling (buscar códigos de razón estándar)
docker compose logs backend | grep -E "(THROTTLED_TIME_GATE|THROTTLED_PRICE_GATE|THROTTLED_MIN_TIME|THROTTLED_MIN_CHANGE|IMMEDIATE_ALERT|CONFIG_CHANGE|ALERT_SENT|ALERT_BLOCKED)"

# Ver logs de creación de órdenes
docker compose logs backend | grep -E "(ORDER_CREATED|ORDER_BLOCKED)"
```

---

## 📝 Notas Importantes

1. **Throttling Fijo de 60 Segundos**: El tiempo mínimo entre alertas es **siempre 60 segundos**, fijo y no configurable. No hay cooldown configurable por moneda o estrategia.

2. **Independencia de Lados**: BUY y SELL son completamente independientes. Cada lado mantiene su propio `baseline_price` y `last_sent_at`. Un cambio de lado NO resetea el throttling del otro lado.

3. **Cambio de Precio Relativo al Baseline**: El throttling verifica el cambio de precio relativo al `baseline_price` de la última alerta enviada, NO a la última orden. Esto permite que las órdenes se creen después de alertas exitosas sin verificar cambio de precio nuevamente.

4. **Alertas vs Órdenes**: Las alertas y las órdenes tienen lógicas independientes. Una alerta puede enviarse sin crear una orden (si `trade_enabled=False`), y una orden solo se crea después de una alerta **enviada exitosamente** (confirmada por Telegram).

5. **Bypass Inmediato Post-Config**: Cuando cambia cualquier parámetro de configuración, el sistema permite una alerta inmediata (bypass de tiempo y precio) para ambos lados independientemente. Después de usar el bypass, vuelve al throttling normal.

6. **Base de Datos como Fuente de Verdad**: El sistema usa `signal_throttle_states` en la base de datos como la única fuente de verdad para el throttling. Esto previene inconsistencias entre procesos.

7. **Nomenclatura de Campos**: La documentación usa nombres canónicos (`baseline_price`, `last_sent_at`, `allow_immediate_after_config_change`), pero el código puede usar alias (`last_price`, `last_time`, `force_next_signal`). Ver sección de "Persistencia de Estado" para mapeo completo.

---

## 📚 Referencias

- `backend/app/services/signal_throttle.py` - Implementación del throttling
- `backend/app/services/signal_monitor.py` - Lógica de alertas y órdenes
- `backend/app/models/signal_throttle.py` - Modelo de datos para `signal_throttle_states`

**Nota**: Este documento es la **fuente de verdad canónica** para las reglas de alertas y órdenes. Otros documentos pueden referenciar lógica antigua o deprecada.


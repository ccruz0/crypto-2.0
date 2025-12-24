# Documentación Actualizada - Alertas y Órdenes

**Fecha:** 2025-01-XX  
**Propósito:** Actualización de documentación para reflejar la lógica canónica nueva de alertas y órdenes

---

## 📋 Archivos Modificados

### 1. Documento Principal (Fuente de Verdad)

- **`docs/ALERTAS_Y_ORDENES_NORMAS.md`** - **COMPLETAMENTE REESCRITO**
  - Actualizado con lógica canónica nueva
  - Throttling fijo de 60 segundos (no configurable)
  - Throttling independiente por (símbolo, lado)
  - Sección de bypass inmediato post-configuración
  - Tabla de verdad con 7 ejemplos concretos
  - Nomenclatura estandarizada de campos

### 2. Documentos con Notas de Deprecación

- **`docs/SIGNAL_THROTTLE_LOG_ANALYSIS.md`**
  - Agregada nota de deprecación al inicio
  - Actualizada referencia a cooldown (ahora fijo 60s)

- **`docs/monitoring/ADA_SELL_ALERT_FLOW_ANALYSIS.md`**
  - Agregada nota de deprecación al inicio
  - Actualizadas referencias a cooldown configurable
  - Actualizada lógica de "cambio de lado resetea throttling" (removida)

- **`docs/monitoring/business_rules_validation.md`**
  - Marcada referencia a `ALERT_COOLDOWN_MINUTES = 5` como deprecada

- **`docs/monitoring/ldo_usd_order_execution_explanation.md`**
  - Actualizada referencia a cooldown de 5 minutos (ahora fijo 60s)

- **`docs/monitoring/LDO_ALERTA_ORDEN_DIAGNOSTICO.md`**
  - Agregada nota de deprecación
  - Actualizada sección de throttle con referencia a lógica nueva

- **`docs/SIGNAL_MONITOR_LOGGING_FIX.md`**
  - Agregada nota histórica (documento de cambios pasados)

- **`docs/SIGNAL_MONITOR_FIX_SUMMARY.md`**
  - Agregada nota histórica (documento de cambios pasados)

---

## 🔄 Resumen de Cambios

### Cambios Principales en Lógica Documentada

1. **Throttling de Tiempo**:
   - ❌ **ANTES**: Configurable (`alert_cooldown_minutes`, default 5 minutos)
   - ✅ **AHORA**: Fijo en **60 segundos** (no configurable)

2. **Granularidad de Throttling**:
   - ✅ **CONFIRMADO**: Independiente por (símbolo, lado)
   - ✅ BUY y SELL son completamente independientes

3. **Cambio de Lado**:
   - ❌ **ANTES**: Cambio de lado (BUY ↔ SELL) resetea throttling
   - ✅ **AHORA**: Los lados son independientes, no hay reset por cambio de lado

4. **Cambio de Configuración**:
   - ✅ **NUEVO**: Cuando cambia cualquier parámetro de configuración:
     - Resetea baseline para ambos lados independientemente
     - Permite bypass inmediato (una vez por lado)
     - Después del bypass, vuelve a throttling normal

5. **Puertas de Throttling**:
   - ✅ **NUEVO**: Orden de verificación:
     1. Primera alerta → Permitida inmediatamente
     2. Puerta de tiempo (60s) → SIEMPRE se verifica primero
     3. Puerta de precio → Solo después de pasar tiempo

6. **Nomenclatura de Campos**:
   - Documentación usa nombres canónicos:
     - `baseline_price` (código: `last_price`)
     - `last_sent_at` (código: `last_time`)
     - `allow_immediate_after_config_change` (código: `force_next_signal`)

---

## ✅ Checklist de Consistencia de Documentación

### ✅ Throttling Fijo de 60s por (símbolo, lado)
- [x] Documento principal actualizado con tiempo fijo
- [x] Referencias a `alert_cooldown_minutes` marcadas como deprecadas
- [x] Referencias a `minIntervalMinutes` marcadas como deprecadas
- [x] Ejemplos actualizados con 60 segundos

### ✅ Puerta de Precio Usa baseline_price
- [x] Documentado uso de `baseline_price` (con nota de alias `last_price` en código)
- [x] Fórmula documentada: `abs((precio_actual - baseline_price) / baseline_price) * 100 >= min_price_change_pct`
- [x] Ejemplos numéricos incluidos (baseline $100, threshold 3%, etc.)

### ✅ Bypass Inmediato Post-Config Documentado
- [x] Sección completa sobre cambio de configuración
- [x] Explicación de reset de baseline para ambos lados
- [x] Explicación de flag `allow_immediate_after_config_change`
- [x] Ejemplos de bypass inmediato incluidos

### ✅ Órdenes Solo Después de Alerta Exitosa
- [x] Documentado que orden requiere alerta enviada exitosamente
- [x] Documentado que NO se re-verifica cambio de precio en creación de orden
- [x] Mapeo BUY alert → BUY order, SELL alert → SELL order

### ✅ Campos TP/SL Documentados
- [x] `take_profit_pct` documentado como campo de estrategia
- [x] `stop_loss_pct` documentado como campo de estrategia
- [x] Ejemplo: TP 3%, SL 2%

### ✅ Tabla de Verdad / Ejemplos
- [x] 7 ejemplos concretos incluidos:
  1. Cambio config → BUY inmediato
  2. Cambio config → SELL inmediato
  3. Bloqueado por tiempo
  4. Bloqueado por precio
  5. Permitido (tiempo + precio OK)
  6. BUY permitido mientras SELL throttled (independencia)
  7. Primera alerta

---

## 🔍 Comandos de Verificación

### Verificar Referencias a Cooldown Configurable (debería mostrar solo notas de deprecación)

```bash
# Buscar referencias a alert_cooldown_minutes (debería mostrar solo en docs históricos con notas)
grep -R "alert_cooldown_minutes" docs/ --include="*.md" | grep -v "DEPRECATED\|HISTORICAL" || echo "✅ Solo referencias deprecadas encontradas"

# Buscar referencias a minIntervalMinutes
grep -R "minIntervalMinutes" docs/ --include="*.md" | grep -v "DEPRECATED\|HISTORICAL" || echo "✅ Solo referencias deprecadas encontradas"

# Buscar referencias a cooldown de 5 minutos
grep -R "5.*minut.*cooldown\|cooldown.*5.*minut" docs/ --include="*.md" -i | grep -v "DEPRECATED\|HISTORICAL" || echo "✅ Solo referencias deprecadas encontradas"
```

### Verificar Referencias a "Cambio de Lado Resetea"

```bash
# Buscar referencias a cambio de lado reseteando throttling
grep -R "change.*side.*reset\|side.*change.*reset\|cambio.*lado.*reset" docs/ --include="*.md" -i | grep -v "DEPRECATED\|NO resetea\|independientes" || echo "✅ Solo referencias corregidas encontradas"
```

### Verificar Nomenclatura de Campos

```bash
# Verificar que baseline_price está documentado
grep -R "baseline_price" docs/ALERTAS_Y_ORDENES_NORMAS.md && echo "✅ baseline_price documentado"

# Verificar que last_sent_at está documentado
grep -R "last_sent_at" docs/ALERTAS_Y_ORDENES_NORMAS.md && echo "✅ last_sent_at documentado"

# Verificar que allow_immediate_after_config_change está documentado
grep -R "allow_immediate_after_config_change" docs/ALERTAS_Y_ORDENES_NORMAS.md && echo "✅ allow_immediate_after_config_change documentado"
```

### Verificar Tabla de Verdad

```bash
# Verificar que hay ejemplos en el documento principal
grep -R "Ejemplo [0-9]:" docs/ALERTAS_Y_ORDENES_NORMAS.md && echo "✅ Ejemplos encontrados"

# Contar ejemplos
grep -c "Ejemplo [0-9]:" docs/ALERTAS_Y_ORDENES_NORMAS.md
```

### Verificar Códigos de Razón

```bash
# Verificar códigos de razón documentados
grep -E "THROTTLED_TIME_GATE|THROTTLED_PRICE_GATE|CONFIG_CHANGE|IMMEDIATE_ALERT|ALERT_SENT|ALERT_BLOCKED|ORDER_CREATED" docs/ALERTAS_Y_ORDENES_NORMAS.md && echo "✅ Códigos de razón documentados"
```

---

## 📝 Notas Adicionales

1. **Documentos Históricos**: Algunos documentos en `docs/monitoring/` y `docs/` son reportes históricos o de diagnóstico. Se agregaron notas de deprecación pero se mantuvieron para referencia histórica.

2. **Nomenclatura Código vs Documentación**: La documentación usa nombres canónicos (`baseline_price`, `last_sent_at`), pero el código puede usar alias (`last_price`, `last_time`). La documentación incluye notas de mapeo.

3. **Fuente de Verdad**: `ALERTAS_Y_ORDENES_NORMAS.md` es ahora la **única fuente de verdad canónica** para las reglas de alertas y órdenes. Otros documentos deben referenciar este documento.

4. **Verificación de Código**: Esta actualización es **solo de documentación**. No se modificó código. Si el código implementa lógica diferente, debe actualizarse para alinearse con esta documentación canónica.

---

## 🎯 Próximos Pasos Recomendados

1. **Auditar Código**: Verificar que el código implementa la lógica documentada:
   - Throttling fijo de 60 segundos
   - Independencia de lados
   - Bypass inmediato post-config
   - Nomenclatura de campos

2. **Actualizar Tests**: Si hay tests que referencian lógica antigua, actualizarlos.

3. **Comunicar Cambios**: Notificar al equipo sobre la nueva lógica canónica y la actualización de documentación.

---

**Documento generado automáticamente como parte de la actualización de documentación canónica.**


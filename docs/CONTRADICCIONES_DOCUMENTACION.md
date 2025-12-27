# 🔍 Informe de Contradicciones en Documentación de Referencia

Este documento identifica contradicciones encontradas al revisar toda la documentación de referencia del proyecto.

**Fecha de revisión**: 2025-01-XX

---

## 🚨 Contradicción Crítica #1: Docker en Producción

### Descripción
Existe una contradicción fundamental sobre el uso de Docker en producción AWS.

### Documentación que dice "NO Docker":
1. **`README.md`** (líneas 9-18):
   - "⚠️ IMPORTANT: All production deployments MUST be done directly via SSH on AWS. Docker is CLOSED and will NOT be used."
   - "✅ All deployments via SSH directly on AWS EC2 instance"
   - "❌ Docker is disabled and NOT to be used for deployments"
   - "❌ No Docker containers or Docker Compose for production"

2. **`DEPLOYMENT_POLICY.md`** (líneas 4-30):
   - "**All deployments MUST be performed directly via SSH on the AWS EC2 instance.**"
   - "Docker is CLOSED and will NOT be used for deployments"
   - "❌ Docker containers are NOT to be used for production deployments"
   - "❌ `docker compose` commands are NOT to be used for deployment"

### Evidencia de que SÍ se usa Docker:
1. **`docker-compose.yml`** contiene perfiles AWS:
   - `backend-aws` (líneas 138-188) - Servicio Docker para AWS
   - `frontend-aws` (líneas 312-362) - Servicio Docker para AWS
   - `market-updater-aws` (líneas 226-275) - Servicio Docker para AWS
   - `db` con perfil `aws` (línea 47)

2. **Múltiples archivos de documentación** usan comandos Docker para AWS:
   - `docs/502_BAD_GATEWAY_REVIEW.md`: `docker compose --profile aws`
   - `docs/AWS_CRYPTO_COM_CONNECTION.md`: `docker compose --profile aws restart backend-aws`
   - `docs/CONFIGURE_DIRECT_CONNECTION.md`: `docker compose --profile aws`
   - Y muchos más...

3. **`README-ops.md`** describe operaciones con Docker para desarrollo local, pero no contradice directamente (solo menciona desarrollo).

### Impacto
Esta contradicción puede causar confusión sobre cómo desplegar en producción. El código y la mayoría de la documentación operativa usan Docker con perfiles AWS, pero la política principal dice que Docker no debe usarse.

### Recomendación
**URGENTE**: Decidir y actualizar la documentación:
- **Opción A**: Si Docker SÍ se usa en producción, actualizar `README.md` y `DEPLOYMENT_POLICY.md` para reflejar que Docker con perfiles AWS es el método correcto.
- **Opción B**: Si Docker NO se debe usar, eliminar los perfiles AWS de `docker-compose.yml` y actualizar toda la documentación que los referencia.

---

## ⚠️ Contradicción Menor #2: `alert_cooldown_minutes` Deprecado

### Descripción
El campo `alert_cooldown_minutes` está marcado como deprecado, pero aún aparece en varios lugares.

### Estado Actual (Correcto):
1. **`docs/ALERTAS_Y_ORDENES_NORMAS.md`** (líneas 84, 226, 416):
   - El throttling de alertas es **fijo en 60 segundos** (no configurable)
   - "**Nota sobre Throttling**: El tiempo mínimo entre alertas es **fijo en 60 segundos** y no es configurable por moneda ni por estrategia."

2. **Código** (`backend/app/services/signal_throttle.py` línea 131):
   - `FIXED_THROTTLE_SECONDS = 60.0  # Fixed by canonical logic (not configurable)`

3. **Documentación de validación** (`docs/monitoring/business_rules_validation.md` línea 120):
   - "⚠️ **DEPRECATED**: `alert_cooldown_minutes` field exists in DB but is not used - throttling is fixed at 60 seconds"

### Lugares donde aún se menciona (puede causar confusión):
1. **`backend/app/models/watchlist.py`** (línea 33):
   - El campo `alert_cooldown_minutes` existe en el modelo de base de datos

2. **`frontend/src/app/page.tsx`** (líneas 454, 8084-8154):
   - Referencias a `alertCooldownMinutes` en la UI con valor por defecto de 5.0
   - Interfaz de usuario permite configurar "Alert Cooldown" (aunque puede no tener efecto)

3. **`backend/trading_config.json`** (líneas 31, 54, 83):
   - Referencias a `alertCooldownMinutes: 5.0` en configuraciones de estrategia

### Impacto
Baja - La funcionalidad funciona correctamente (usa 60 segundos fijos), pero puede confundir a los usuarios que vean referencias a configuración de cooldown.

### Recomendación
- Marcar claramente en la UI que el cooldown de alertas es fijo (60s) y no configurable
- Considerar eliminar el campo de la UI si no se usa
- El campo en la base de datos puede mantenerse por compatibilidad, pero debe documentarse claramente como "legacy/deprecated"

---

## ✅ Verificaciones que están Correctas

### 1. Throttling de Alertas: 60 segundos
- ✅ `docs/ALERTAS_Y_ORDENES_NORMAS.md`: 60 segundos fijo
- ✅ `backend/app/services/signal_throttle.py`: 60 segundos fijo
- ✅ Múltiples documentos de referencia: 60 segundos fijo

### 2. Cooldown de Órdenes: 5 minutos
- ✅ `docs/ALERTAS_Y_ORDENES_NORMAS.md` (línea 128): "Cooldown de 5 Minutos"
- ✅ `backend/app/services/signal_monitor.py` (línea 1800): `timedelta(minutes=5)`
- ✅ Consistente en toda la documentación

### 3. Máximo de Órdenes Abiertas: 3 por símbolo
- ✅ `docs/ALERTAS_Y_ORDENES_NORMAS.md` (línea 124): "Máximo 3 órdenes abiertas por símbolo"
- ✅ `docs/LIMITE_ORDENES_ABIERTAS.md`: Documentación completa sobre el límite de 3
- ✅ `backend/app/services/signal_monitor.py` (línea 60): `MAX_OPEN_ORDERS_PER_SYMBOL = 3`

### 4. Cambio de Precio Mínimo para Alertas
- ✅ Variable según estrategia (`min_price_change_pct`)
- ✅ Documentado correctamente en `ALERTAS_Y_ORDENES_NORMAS.md`
- ✅ Consistente con el código

---

## 📋 Resumen Ejecutivo

### Contradicciones Críticas
1. **Docker en Producción** - Documentación oficial dice que NO se usa, pero el código y operaciones SÍ lo usan

### Contradicciones Menores / Áreas de Mejora
1. **`alert_cooldown_minutes`** - Campo deprecado pero aún visible en UI y modelos

### Estado General
- La mayoría de las reglas de negocio (throttling, límites de órdenes) están **correctamente documentadas y son consistentes**
- El problema principal es la contradicción sobre el método de deployment (Docker vs SSH directo)
- Los campos deprecados deberían limpiarse o marcarse más claramente

---

## 🎯 Acciones Recomendadas (Priorizadas)

### Prioridad 1: CRÍTICA
1. **Resolver contradicción de Docker**:
   - Revisar el estado actual en AWS (¿se usa Docker o procesos directos?)
   - Actualizar `README.md` y `DEPLOYMENT_POLICY.md` para reflejar la realidad
   - O migrar a SSH directo si esa es la decisión estratégica

### Prioridad 2: IMPORTANTE
2. **Limpiar referencias a `alert_cooldown_minutes`**:
   - Actualizar UI para mostrar que es fijo (60s) y no configurable
   - Agregar notas claras de "DEPRECATED" donde aún aparezca
   - Documentar que el campo en BD se mantiene solo por compatibilidad

### Prioridad 3: MEJORA
3. **Revisar documentación operativa**:
   - Asegurar que todos los comandos de deployment sean consistentes
   - Actualizar guías que aún mencionen métodos antiguos

---

**Última actualización**: 2025-01-XX
**Próxima revisión recomendada**: Después de resolver contradicción crítica #1







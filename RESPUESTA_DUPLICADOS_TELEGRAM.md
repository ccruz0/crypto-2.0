# ¿Recibiré notificaciones duplicadas si habilito Telegram en local?

## Respuesta Corta

**Sí, podrías recibir notificaciones duplicadas** si tienes **dos servicios backend corriendo simultáneamente** (uno local y uno aws).

## Análisis del Sistema

### Mecanismos de Deduplicación Existentes

1. **Verificación en Base de Datos** (líneas 567-578 de `exchange_sync.py`):
   - Antes de crear SL/TP, verifica si ya existen en la base de datos
   - Previene la creación duplicada de **órdenes SL/TP**

2. **Lock en Memoria** (`_sl_tp_creation_locks`):
   - Previene creación concurrente dentro de la **misma instancia** del servicio
   - No funciona entre múltiples instancias

3. **Tracking de Órdenes Procesadas** (`processed_order_ids`):
   - Rastrea órdenes ya procesadas por instancia
   - No es compartido entre múltiples servicios

### El Problema

Si tienes **dos servicios backend corriendo simultáneamente**:

```
Servicio Local (backend)          Servicio AWS (backend-aws)
─────────────────────────         ─────────────────────────
1. Detecta orden ejecutada        1. Detecta orden ejecutada
2. Verifica BD: ¿SL/TP existen?   2. Verifica BD: ¿SL/TP existen?
   → NO (aún no creados)             → NO (aún no creados)
3. Crea SL/TP                     3. Crea SL/TP
4. Envía notificación Telegram    4. Envía notificación Telegram
```

**Resultado**: Recibirías **2 notificaciones** para la misma orden.

### ¿Cuándo NO habrá duplicados?

✅ **Si solo hay UN servicio corriendo**:
- Solo `backend` (local) O solo `backend-aws` (aws)
- No habrá duplicados porque solo una instancia procesa las órdenes

✅ **Si el segundo servicio detecta la orden después**:
- Si el primer servicio ya creó los SL/TP y los guardó en la BD
- El segundo servicio verá que ya existen y no creará nuevos
- **PERO**: Si ambos detectan la orden al mismo tiempo, ambos enviarán notificación

## Recomendación

### Opción 1: Usar Solo Un Servicio (Recomendado)

**Para producción**: Usa solo `backend-aws`
```bash
# Detener servicios locales
docker compose --profile local down

# Iniciar solo servicios AWS
docker compose --profile aws up -d
```

**Para desarrollo**: Usa solo `backend` (local)
```bash
# Detener servicios AWS
docker compose --profile aws down

# Iniciar solo servicios locales
docker compose --profile local up -d
```

### Opción 2: Habilitar Telegram Solo en Uno

Si necesitas ambos servicios corriendo:
- **Habilitar Telegram solo en `backend-aws`** (producción)
- **Mantener `RUN_TELEGRAM=false` en `backend`** (local)

### Opción 3: Agregar Deduplicación de Notificaciones (Futuro)

Se podría agregar un mecanismo de deduplicación a nivel de base de datos para las notificaciones:
- Guardar un registro de notificaciones enviadas
- Verificar antes de enviar si ya se envió una notificación para esa orden
- Esto requeriría cambios en el código

## Verificación Actual

Para verificar si tienes múltiples servicios corriendo:

```bash
# Ver todos los servicios backend
docker compose ps | grep backend

# O
docker ps | grep backend
```

Si ves **más de un servicio backend**, podrías recibir notificaciones duplicadas.

## Conclusión

**Sí, recibirás notificaciones duplicadas** si:
- Tienes `backend` (local) y `backend-aws` corriendo simultáneamente
- Ambos tienen `RUN_TELEGRAM=true`
- Ambos detectan la misma orden ejecutada al mismo tiempo

**Solución**: Usa solo un servicio a la vez, o habilita Telegram solo en el servicio de producción (`backend-aws`).







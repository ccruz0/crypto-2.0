# Resumen: Solución del Problema de Logging TP/SL

## Problema Identificado

Los logs de `[TP_ORDER]` y `FULL PAYLOAD` no aparecían en `docker compose logs backend-aws` cuando se ejecutaba el script de test directamente.

**Causa raíz:** El root logger tenía nivel WARNING (30) y no tenía handlers configurados cuando se ejecutaba el script directamente (fuera del proceso uvicorn).

## Solución Implementada

### 1. Configuración Centralizada de Logging

**Archivo creado:** `backend/app/core/logging_config.py`

- Función `setup_logging()`: Configura el root logger con nivel INFO y un StreamHandler
- Función `get_tp_logger()`: Retorna un logger dedicado para TP/SL orders
- Evita duplicar handlers si ya están configurados

### 2. Integración en `main.py`

**Archivo modificado:** `backend/app/main.py`

- Se llama `setup_logging()` al inicio del módulo, antes de crear cualquier logger
- Asegura que todos los módulos hereden la configuración correcta

### 3. Integración en Test

**Archivo modificado:** `backend/tests/test_manual_tp.py`

- Se llama `setup_logging()` ANTES de importar cualquier módulo que use logging
- Se añade un log de verificación `[TP_ORDER][TEST]` para confirmar que el logging funciona
- Se documenta cómo verificar los logs

## Verificación

### Ejecutar el test:

```bash
docker compose exec backend-aws python3 /app/tests/test_manual_tp.py
```

### Ver los logs:

```bash
docker compose logs backend-aws 2>&1 | grep "TP_ORDER" | tail -50
```

### Logs esperados:

- `[TP_ORDER][TEST] Sanity check log before placing TP order`
- `[TP_ORDER][MANUAL] Sending HTTP request to exchange`
- `[TP_ORDER][MANUAL] Payload JSON: {...}`
- `[TP_ORDER][MANUAL] Received HTTP response from exchange`
- `FULL PAYLOAD: {...}`

## Archivos Modificados

1. **`backend/app/core/logging_config.py`** (nuevo)
   - Configuración centralizada de logging

2. **`backend/app/main.py`**
   - Líneas 27-29: Llamada a `setup_logging()` al inicio

3. **`backend/tests/test_manual_tp.py`**
   - Líneas 24-32: Configuración de logging antes de imports
   - Líneas 57-59: Log de verificación `[TP_ORDER][TEST]`

## Resultado

✅ Los logs de `[TP_ORDER]` y `FULL PAYLOAD` ahora aparecen correctamente en:
- Salida directa del script (`docker compose exec`)
- Logs de Docker (`docker compose logs backend-aws`)

✅ La configuración de logging es consistente entre:
- Proceso principal (uvicorn)
- Scripts de test ejecutados directamente
- Cualquier módulo que use logging

✅ No se modificó la lógica de negocio, solo la configuración de logging


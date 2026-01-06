# Diagnóstico del Error del Backend

## Problema Identificado

El backend está fallando al iniciar con el siguiente error:

```
ModuleNotFoundError: No module named 'pydantic_settings'
```

## Estado Actual

- ✅ **Contenedor**: Corriendo (Up 2 seconds, health: starting)
- ✅ **Gunicorn instalado**: Sí (versión 21.2.0)
- ❌ **Gunicorn corriendo**: No (worker falla al iniciar)
- ❌ **pydantic-settings instalado**: No (aunque está en requirements.txt)
- ❌ **Health endpoint**: No responde (503)

## Causa Raíz

El módulo `pydantic-settings` está listado en `requirements.txt` (línea 29: `pydantic-settings==2.5.2`) pero **no se instaló correctamente en la imagen Docker**.

El error ocurre cuando gunicorn intenta iniciar el worker:
1. Gunicorn intenta cargar `app.main:app`
2. `app/main.py` importa `app.core.config`
3. `app/core/config.py` intenta importar `from pydantic_settings import BaseSettings`
4. **FALLA**: `ModuleNotFoundError: No module named 'pydantic_settings'`

## Análisis del Dockerfile

El Dockerfile tiene dos pasos de instalación:

1. **Líneas 49-51**: Instalación desde wheels
   ```dockerfile
   RUN pip install --no-cache-dir --no-index --find-links /wheels -r requirements.txt || \
       (echo "WARNING: Some packages not found in wheels, installing from PyPI..." && \
        pip install --no-cache-dir -r requirements.txt)
   ```

2. **Línea 55**: Instalación de fallback
   ```dockerfile
   RUN pip install --no-cache-dir -r requirements.txt || true
   ```

El problema es que si la instalación desde wheels falla silenciosamente o si `pydantic-settings` no está en los wheels, puede que no se instale correctamente.

## Solución

### Opción 1: Reconstruir la imagen (Recomendado)

Ejecutar el script de fix que ya existe:

```bash
./fix_backend_docker_build.sh
```

Este script:
1. Limpia contenedores e imágenes antiguas
2. Reconstruye con `--no-cache`
3. Verifica que gunicorn esté instalado
4. Verifica que el contenedor inicie correctamente

### Opción 2: Instalación manual en contenedor (Temporal)

Si necesitas una solución rápida temporal:

```bash
# En el servidor AWS
docker compose --profile aws exec backend-aws pip install pydantic-settings==2.5.2
docker compose --profile aws restart backend-aws
```

**Nota**: Esta solución es temporal porque se perderá al reconstruir la imagen.

### Opción 3: Verificar instalación de dependencias

Verificar qué paquetes están instalados:

```bash
docker compose --profile aws exec backend-aws pip list | grep pydantic
```

Debería mostrar:
```
pydantic           2.9.2
pydantic-settings  2.5.2
```

## Verificación Post-Fix

Después de aplicar la solución, verificar:

1. **Contenedor corriendo**:
   ```bash
   docker compose --profile aws ps backend-aws
   ```
   Debe mostrar: `Up X minutes (healthy)`

2. **Gunicorn corriendo**:
   ```bash
   docker compose --profile aws exec backend-aws ps aux | grep gunicorn
   ```
   Debe mostrar procesos de gunicorn

3. **Health endpoint**:
   ```bash
   curl http://localhost:8002/ping_fast
   ```
   Debe responder: `pong` o similar

4. **Dashboard endpoint**:
   ```bash
   curl http://localhost:8002/api/dashboard/state | head -c 200
   ```
   Debe devolver JSON con datos del dashboard

## Próximos Pasos

1. ✅ Ejecutar `./fix_backend_docker_build.sh` para reconstruir la imagen
2. ✅ Verificar que todas las dependencias se instalen correctamente
3. ✅ Verificar que el backend responda correctamente
4. ✅ Verificar que el dashboard muestre datos del portfolio

## Nota sobre el Dockerfile

El Dockerfile tiene instalación duplicada (líneas 49-51 y 55). Esto puede causar problemas si la primera instalación falla silenciosamente. Se recomienda:

1. Asegurar que la instalación desde wheels funcione correctamente
2. O simplificar a una sola instalación con fallback apropiado
3. Verificar que todos los paquetes de requirements.txt se instalen





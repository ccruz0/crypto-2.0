# Fix para pydantic-settings no instalado

## Problema

El backend falla con:
```
ModuleNotFoundError: No module named 'pydantic_settings'
```

Aunque `pydantic-settings==2.5.2` está en `requirements.txt`, no se está instalando correctamente en la imagen Docker.

## Corrección Aplicada

Se modificó el Dockerfile para:

1. **Instalación explícita de pydantic-settings**: Se agregó un paso que instala explícitamente `pydantic-settings==2.5.2`
2. **Verificación**: Se verifica que el módulo se pueda importar correctamente
3. **Fallo explícito**: Si la instalación falla, el build falla (en lugar de continuar silenciosamente)

### Cambios en Dockerfile

**Antes**:
```dockerfile
RUN pip install --no-cache-dir --no-index --find-links /wheels -r requirements.txt || \
    (echo "WARNING: Some packages not found in wheels, installing from PyPI..." && \
     pip install --no-cache-dir -r requirements.txt)

RUN pip install --no-cache-dir -r requirements.txt || true
```

**Después**:
```dockerfile
RUN pip install --no-cache-dir --no-index --find-links /wheels -r requirements.txt 2>&1 | tee /tmp/wheel_install.log || \
    (echo "WARNING: Some packages not found in wheels, installing from PyPI..." && \
     pip install --no-cache-dir -r requirements.txt)

# Ensure critical packages are installed (explicit verification)
# Verify pydantic-settings is installed (critical dependency)
RUN pip install --no-cache-dir pydantic-settings==2.5.2 && \
    python -c "import pydantic_settings; print('pydantic-settings installed successfully')" || \
    (echo "ERROR: pydantic-settings installation failed" && exit 1)
```

## Próximos Pasos

1. Reconstruir la imagen Docker con el Dockerfile corregido:
   ```bash
   ./fix_backend_docker_build.sh
   ```

2. Verificar que pydantic-settings esté instalado:
   ```bash
   docker compose --profile aws exec backend-aws pip list | grep pydantic
   ```

3. Verificar que el backend inicie correctamente:
   ```bash
   docker compose --profile aws logs backend-aws | grep -i "pydantic\|error"
   ```

## Verificación

Después de reconstruir, verificar:

- ✅ `pydantic-settings` aparece en `pip list`
- ✅ El backend inicia sin errores de importación
- ✅ El health endpoint responde correctamente
- ✅ El dashboard puede obtener datos del backend





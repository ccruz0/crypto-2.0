# 📤 Subir Scripts de Diagnóstico a AWS

## Opción 1: Usar el Script Automático (Recomendado)

```bash
# Desde el directorio raíz del proyecto
./upload_diagnostics_to_aws.sh
```

## Opción 2: Subir Manualmente con rsync

```bash
# Subir todos los scripts de diagnóstico
rsync -avz backend/scripts/test_script_works.py \
           backend/scripts/deep_auth_diagnostic.py \
           backend/scripts/diagnose_auth_40101.py \
           backend/scripts/test_crypto_connection.py \
           backend/scripts/verify_api_key_setup.py \
           ubuntu@47.130.143.159:~/automated-trading-platform/backend/scripts/
```

## Opción 3: Subir Todo el Directorio de Scripts

```bash
# Subir todo el directorio scripts (más completo)
rsync -avz backend/scripts/ ubuntu@47.130.143.159:~/automated-trading-platform/backend/scripts/
```

## Opción 4: Usar scp (Si no tienes rsync)

```bash
# Subir cada archivo individualmente
scp backend/scripts/test_script_works.py ubuntu@47.130.143.159:~/automated-trading-platform/backend/scripts/
scp backend/scripts/deep_auth_diagnostic.py ubuntu@47.130.143.159:~/automated-trading-platform/backend/scripts/
scp backend/scripts/diagnose_auth_40101.py ubuntu@47.130.143.159:~/automated-trading-platform/backend/scripts/
scp backend/scripts/test_crypto_connection.py ubuntu@47.130.143.159:~/automated-trading-platform/backend/scripts/
```

## Después de Subir

Una vez subidos, haz los scripts ejecutables:

```bash
ssh ubuntu@47.130.143.159 "chmod +x ~/automated-trading-platform/backend/scripts/*.py"
```

## Verificar que se Subieron

```bash
ssh ubuntu@47.130.143.159 "ls -la ~/automated-trading-platform/backend/scripts/test_script_works.py"
```

Deberías ver el archivo listado.

## Luego Ejecutar

```bash
ssh ubuntu@47.130.143.159 "cd ~/automated-trading-platform/backend && python3 scripts/test_script_works.py"
```


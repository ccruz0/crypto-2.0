# Operations Guide

This document provides operational instructions for running the automated trading platform locally and in production.

## Arranque local con secrets

### 1. Configurar secrets de Postgres

```bash
cd /Users/carloscruz/automated-trading-platform

mkdir -p secrets

printf "CHANGE_ME_STRONG_PASSWORD_64" > secrets/pg_password

chmod 600 secrets/pg_password
```

**⚠️ IMPORTANTE**: Reemplaza `CHANGE_ME_STRONG_PASSWORD_64` con una contraseña segura antes de usar en producción.

### 2. Iniciar servicios

```bash
cd /Users/carloscruz/automated-trading-platform

docker compose up -d --build
```

### 3. Verificar estado de servicios

```bash
cd /Users/carloscruz/automated-trading-platform

docker compose ps
```

### 4. Ver logs de base de datos

```bash
cd /Users/carloscruz/automated-trading-platform

docker compose logs -f db
```

## Configuración de Secrets

Los secrets de Postgres se gestionan mediante Docker Compose secrets:

- **Ubicación**: `./secrets/pg_password`
- **Permisos**: `600` (solo lectura para el propietario)
- **No se incluye en git**: El directorio `secrets/` está en `.gitignore`

### Estructura de secrets

```
secrets/
  └── pg_password          # Contraseña de PostgreSQL (NO commitear)
```

## Variables de Entorno

Las contraseñas se gestionan mediante secrets en lugar de variables de entorno para mayor seguridad:

- `POSTGRES_PASSWORD_FILE`: Apunta a `/run/secrets/pg_password` dentro del contenedor
- `POSTGRES_INITDB_ARGS`: Configura autenticación scram-sha-256

## Verificación de Seguridad

### Healthchecks

Todos los servicios incluyen healthchecks configurados:

- **Frontend**: Verifica que el servidor responda en `http://localhost:3000/`
- **Backend**: Verifica que el servidor escuche en el puerto 8000
- **Database**: Verifica que PostgreSQL esté listo con `pg_isready`

### Configuración de Seguridad

Los servicios están configurados con:

- `security_opt: no-new-privileges:true`: Previene escalada de privilegios
- `cap_drop: ALL`: Elimina todas las capacidades del kernel
- `read_only: true`: Sistema de archivos de solo lectura (excepto tmpfs)
- `tmpfs: /tmp`: Montaje temporal para directorios de escritura
- **Límites de recursos**: CPU y memoria limitadas por servicio

## Troubleshooting

### El contenedor no inicia

1. Verifica que el secret existe:
   ```bash
   ls -la secrets/pg_password
   ```

2. Verifica los permisos:
   ```bash
   chmod 600 secrets/pg_password
   ```

3. Verifica los logs:
   ```bash
   docker compose logs db
   ```

### Problemas de conectividad

1. Verifica que los servicios estén healthy:
   ```bash
   docker compose ps
   ```

2. Verifica la salud de cada servicio:
   ```bash
   docker inspect <container_name> | grep -A 10 Health
   ```

## Producción

Para producción:

1. **Genera una contraseña segura**:
   ```bash
   openssl rand -base64 32 > secrets/pg_password
   chmod 600 secrets/pg_password
   ```

2. **Usa secrets management**:
   - Docker Swarm secrets
   - Kubernetes secrets
   - AWS Secrets Manager
   - HashiCorp Vault

3. **Rotación de secrets**:
   - Cambia la contraseña regularmente
   - Actualiza `secrets/pg_password`
   - Reinicia los servicios: `docker compose restart db`


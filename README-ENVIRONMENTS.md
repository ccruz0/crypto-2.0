# Configuración de Entornos (Local y AWS)

Este proyecto está configurado para funcionar en **ambos entornos** (local y AWS) usando Docker Compose profiles.

## 🏗️ Arquitectura

Los servicios están configurados con profiles para poder correr en ambos entornos:
- **Local**: En tu Mac/Linux local
- **AWS**: En una instancia EC2 de AWS

## 📋 Archivos de Configuración

### Variables de Entorno

El proyecto usa archivos `.env` para configurar cada entorno:

- **`.env`**: Variables comunes (compartidas entre local y AWS)
- **`.env.local`**: Variables específicas para entorno local
- **`.env.aws`**: Variables específicas para entorno AWS

### Estructura de Variables

#### `.env` (Común)
```bash
# Database
POSTGRES_DB=atp
POSTGRES_USER=trader
POSTGRES_PASSWORD=traderpass

# Común para ambos entornos
```

#### `.env.local` (Solo Local)
```bash
# Environment
ENVIRONMENT=local

# API URLs
API_BASE_URL=http://localhost:8002
FRONTEND_URL=http://localhost:3000
NEXT_PUBLIC_API_URL=http://localhost:8002/api
NEXT_PUBLIC_ENVIRONMENT=local

# Database (usando Docker Compose service name)
DATABASE_URL=postgresql://trader:traderpass@db:5432/atp
```

#### `.env.aws` (Solo AWS)
```bash
# Environment
ENVIRONMENT=aws

# API URLs (usar IP pública de EC2 o dominio)
API_BASE_URL=http://47.130.143.159:8002
FRONTEND_URL=http://47.130.143.159:3000
NEXT_PUBLIC_API_URL=http://47.130.143.159:8002/api
NEXT_PUBLIC_ENVIRONMENT=aws

# Database (usar IP o service name según configuración)
DATABASE_URL=postgresql://trader:traderpass@db:5432/atp
```

## 🚀 Comandos para Ejecutar

### Local (en tu Mac)

```bash
# Levantar stack local (servicios explícitos — evita choque :8002 entre backend y backend-dev)
docker compose --profile local up -d db backend-dev frontend

# Ver logs
docker compose --profile local logs -f backend-dev frontend

# Detener servicios
docker compose --profile local down
```

> **Nota:** No uses `docker compose --profile local up -d` sin listar servicios:
> `backend` y `backend-dev` comparten el perfil `local` y ambos publican `:8002`.

### AWS (en EC2)

```bash
# Levantar todos los servicios en modo AWS
docker compose --profile aws up -d

# Ver logs
docker compose --profile aws logs -f

# Detener servicios
docker compose --profile aws down
```

## 🔄 Cómo Funciona

1. **Docker Compose Profiles**: Los servicios tienen `profiles: ["local", "aws"]`, lo que permite ejecutarlos con diferentes configuraciones.

2. **Detección Automática**: 
   - **Backend**: Lee la variable `ENVIRONMENT` de los archivos `.env` para detectar el entorno
   - **Frontend**: Detecta automáticamente el entorno basándose en `window.location.hostname` y variables de entorno

3. **Variables de Entorno**: Cada servicio carga:
   - Primero `.env` (común)
   - Luego `.env.local` o `.env.aws` según el entorno
   - Las variables de `.env.local` o `.env.aws` sobrescriben las comunes

## 📝 Notas Importantes

- **Cambios se aplican en ambos entornos**: Todos los cambios de código funcionan en ambos entornos automáticamente
- **Configuración específica**: Usa los archivos `.env.local` y `.env.aws` para diferencias entre entornos
- **Código compartido**: El código es el mismo, solo cambian las variables de entorno

## 🛠️ Desarrollo

Para desarrollo local:
1. Asegúrate de tener `.env` y `.env.local` configurados
2. Ejecuta: `docker compose --profile local up -d db backend-dev frontend`
3. Accede a: `http://localhost:3000`

Para desplegar en AWS:
1. Asegúrate de tener `.env` y `.env.aws` configurados en la instancia EC2
2. Ejecuta: `docker compose --profile aws up -d`
3. Accede a: `https://dashboard.hilovivo.com` (o `http://47.130.143.159:3000`)


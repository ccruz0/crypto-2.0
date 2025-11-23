# 🚀 Guía de Desarrollo Local

## ¿Por qué desarrollar localmente?

✅ **Más rápido**: Sin latencia de red ni SSH  
✅ **Debugging fácil**: Logs y breakpoints en tiempo real  
✅ **Menos costos**: No consumes recursos de AWS mientras desarrollas  
✅ **Más seguro**: Pruebas locales antes de tocar producción  
✅ **Control**: Cambios controlados antes de desplegar  

---

## 🏁 Inicio Rápido

### 1. Iniciar el entorno local

```bash
./dev_local.sh
```

Este script:
- ✅ Verifica que Docker esté corriendo
- ✅ Crea archivos `.env` si no existen
- ✅ Levanta los servicios con el perfil `local`
- ✅ Muestra el estado de los servicios

### 2. Verificar que todo funciona

```bash
# Backend
curl http://localhost:8002/ping_fast

# Frontend
open http://localhost:3000
```

---

## 📋 Comandos Útiles

### Gestión de Servicios

```bash
# Ver logs en tiempo real
docker compose --profile local logs -f

# Ver logs de un servicio específico
docker compose --profile local logs -f backend
docker compose --profile local logs -f frontend
docker compose --profile local logs -f db

# Detener servicios
docker compose --profile local down

# Reiniciar un servicio
docker compose --profile local restart backend
docker compose --profile local restart frontend

# Reconstruir un servicio
docker compose --profile local build backend
docker compose --profile local up -d backend
```

### Base de Datos

```bash
# Conectar a la base de datos
docker compose --profile local exec db psql -U trader -d atp

# Ver datos de tablas
docker compose --profile local exec db psql -U trader -d atp -c "SELECT * FROM watchlist_items LIMIT 5;"
```

### Desarrollo Frontend

```bash
# El frontend está montado como volumen, los cambios se reflejan automáticamente
# Solo necesitas refrescar el navegador

# Ver logs del frontend
docker compose --profile local logs -f frontend

# Entrar al contenedor del frontend (si necesitas)
docker compose --profile local exec frontend sh
```

### Desarrollo Backend

```bash
# El backend está montado como volumen, los cambios se reflejan automáticamente
# Para cambios en Python, puede que necesites reiniciar:
docker compose --profile local restart backend

# Ver logs del backend
docker compose --profile local logs -f backend

# Entrar al contenedor del backend
docker compose --profile local exec backend sh

# Ejecutar comandos Python dentro del contenedor
docker compose --profile local exec backend python -c "from app.services import something; print('OK')"
```

---

## 🔄 Flujo de Trabajo Recomendado

### 1. Desarrollo Local

```bash
# 1. Iniciar entorno local
./dev_local.sh

# 2. Hacer cambios en el código
# - Frontend: Los cambios se reflejan automáticamente (hot reload)
# - Backend: Puede necesitar reinicio para cambios en Python

# 3. Probar localmente
# - Abrir http://localhost:3000
# - Probar endpoints en http://localhost:8002/api

# 4. Verificar logs si hay problemas
docker compose --profile local logs -f
```

### 2. Deploy a AWS (después de probar localmente)

```bash
# Desplegar cambios a AWS
./deploy_to_aws.sh
```

Este script:
- ✅ Sincroniza tu código local con AWS
- ✅ Reconstruye las imágenes Docker en el servidor
- ✅ Reinicia los servicios en AWS
- ✅ Verifica que los servicios estén saludables

---

## 🛠️ Solución de Problemas

### Docker Desktop no está corriendo

```bash
# Inicia Docker Desktop desde la aplicación
# Luego verifica:
docker info
```

### Puerto ya en uso

```bash
# Ver qué está usando el puerto
lsof -i :8002  # Backend
lsof -i :3000  # Frontend
lsof -i :5432  # Database

# Detener servicios locales
docker compose --profile local down
```

### Base de datos no se conecta

```bash
# Verificar que la base de datos esté corriendo
docker compose --profile local ps db

# Ver logs de la base de datos
docker compose --profile local logs db

# Reiniciar la base de datos
docker compose --profile local restart db
```

### Cambios no se reflejan

```bash
# Frontend: Refresca el navegador (hard refresh: Cmd+Shift+R)

# Backend: Reinicia el servicio
docker compose --profile local restart backend

# Si persiste, reconstruye:
docker compose --profile local build backend
docker compose --profile local up -d backend
```

---

## 🔐 Variables de Entorno

### Archivos de configuración

- `.env` - Configuración base (compartida)
- `.env.local` - Configuración local (no se sube a git)

### Variables importantes para desarrollo local

```env
ENVIRONMENT=local
LIVE_TRADING=false  # ⚠️ IMPORTANTE: false para desarrollo
NODE_ENV=development
DATABASE_URL=postgresql://trader:traderpass@db:5432/atp
```

⚠️ **IMPORTANTE**: Asegúrate de que `LIVE_TRADING=false` en `.env.local` para evitar hacer trades reales durante desarrollo.

---

## 📊 Estructura de Puertos

| Servicio | Puerto Local | URL Local |
|----------|-------------|-----------|
| Backend  | 8002        | http://localhost:8002 |
| Frontend | 3000        | http://localhost:3000 |
| Database | 5432        | localhost:5432 |

---

## 🎯 Comparación: Local vs AWS

| Aspecto | Local | AWS |
|---------|-------|-----|
| Velocidad | ⚡ Muy rápido | 🐢 Lento (SSH/latencia) |
| Debugging | ✅ Fácil | ❌ Difícil |
| Costo | ✅ Gratis | 💰 Consume recursos |
| Seguridad | ✅ Aislado | ⚠️ Producción |
| Testing | ✅ Ideal | ❌ No recomendado |

---

## 📝 Próximos Pasos

1. ✅ Configura tu entorno local: `./dev_local.sh`
2. ✅ Haz cambios y pruébalos localmente
3. ✅ Cuando estés listo: `./deploy_to_aws.sh`

¡Happy coding! 🚀


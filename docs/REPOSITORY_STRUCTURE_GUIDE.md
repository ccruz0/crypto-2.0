# Guía de Estructura de Repositorios

## 📦 Estructura Actual

Tienes **DOS repositorios separados**:

### 1. **`crypto-2.0`** (Repositorio Principal)
- **Ubicación local**: `/Users/carloscruz/crypto-2.0`
- **GitHub**: `https://github.com/ccruz0/crypto-2.0`
- **Contiene**:
  - ✅ `backend/` - Código Python/FastAPI
  - ✅ `frontend/` - **PERO** frontend tiene su propio `.git` (repositorio anidado)
  - ✅ `.github/workflows/` - GitHub Actions
  - ✅ `docker-compose.yml` - Configuración de servicios
  - ✅ `scripts/` - Scripts de deployment y utilidades
  - ✅ `docs/` - Documentación
  - ✅ Archivos de configuración del proyecto

### 2. **`frontend`** (Repositorio Separado)
- **Ubicación local**: `/Users/carloscruz/crypto-2.0/frontend`
- **GitHub**: `https://github.com/ccruz0/frontend` (probablemente)
- **Contiene**:
  - ✅ Código Next.js/TypeScript
  - ✅ `src/` - Código fuente del frontend
  - ✅ `package.json` - Dependencias Node.js
  - ✅ `Dockerfile` - Imagen Docker del frontend
  - ✅ Configuración de Next.js

## ⚠️ Problema Actual

**El directorio `frontend/` tiene su propio `.git/`**, lo que significa que:
- Es un repositorio git independiente
- Los cambios en `frontend/` NO se commitean automáticamente en `crypto-2.0`
- Necesitas hacer commit en AMBOS repositorios por separado

## 📝 ¿Qué Archivo Va a Cada Repositorio?

### **Repositorio `crypto-2.0`** (Principal)
```
automated-trading-platform/
├── backend/              ✅ Va aquí
├── .github/workflows/    ✅ Va aquí
├── docker-compose.yml    ✅ Va aquí
├── scripts/              ✅ Va aquí
├── docs/                 ✅ Va aquí
├── .env*                 ✅ Va aquí (pero NO commiteado)
├── docker/               ✅ Va aquí
└── frontend/             ⚠️  Es un subdirectorio pero tiene su propio git
```

### **Repositorio `frontend`** (Separado)
```
frontend/
├── src/                  ✅ Va aquí
├── public/               ✅ Va aquí
├── package.json          ✅ Va aquí
├── Dockerfile            ✅ Va aquí
├── next.config.ts        ✅ Va aquí
└── tsconfig.json         ✅ Va aquí
```

## 🔄 Flujo de Trabajo Recomendado

### Cuando trabajas en **Backend** o **Configuración**:
```bash
# Estás en: automated-trading-platform/
cd /Users/carloscruz/crypto-2.0

# Hacer cambios en backend, scripts, workflows, etc.
git add .
git commit -m "tus cambios"
git push origin main
```

### Cuando trabajas en **Frontend**:
```bash
# Opción 1: Trabajar directamente en el repo frontend
cd /Users/carloscruz/crypto-2.0/frontend
git add .
git commit -m "cambios en frontend"
git push origin main  # o la rama que uses

# Opción 2: Si quieres actualizar el repo principal también
cd /Users/carloscruz/crypto-2.0
git add frontend  # Esto actualiza la referencia al submodule
git commit -m "update frontend submodule"
git push origin main
```

## 🎯 Recomendaciones

### Opción A: Mantener Separados (Actual)
**Ventajas:**
- Separación clara de responsabilidades
- Puedes trabajar en frontend independientemente
- Diferentes equipos pueden trabajar en cada repo

**Desventajas:**
- Necesitas hacer commit en dos lugares
- Puede ser confuso saber dónde va cada archivo
- Deployment requiere sincronizar ambos

### Opción B: Unificar en un Solo Repositorio (Recomendado)
**Ventajas:**
- Un solo lugar para todo el código
- Deployment más simple
- Menos confusión sobre dónde van los archivos
- Historial unificado

**Desventajas:**
- Repositorio más grande
- Menos separación de responsabilidades

## 🔧 Cómo Unificar (Si decides hacerlo)

Si quieres unificar todo en `crypto-2.0`:

```bash
# 1. Eliminar el .git de frontend
cd /Users/carloscruz/crypto-2.0/frontend
rm -rf .git

# 2. Agregar frontend al repo principal
cd /Users/carloscruz/crypto-2.0
git add frontend/
git commit -m "unify: move frontend into main repository"
git push origin main
```

**⚠️ IMPORTANTE**: Antes de hacer esto, asegúrate de:
1. Hacer backup de ambos repositorios
2. Pushear todos los cambios pendientes en `frontend`
3. Verificar que no pierdes historial importante

## 📋 Checklist de Archivos

### ✅ **Siempre va a `crypto-2.0`:**
- Cualquier archivo en `backend/`
- Cualquier archivo en `scripts/`
- Cualquier archivo en `.github/`
- `docker-compose.yml`
- Archivos de configuración en la raíz (`.env.example`, etc.)
- Documentación en `docs/`

### ✅ **Siempre va a `frontend`:**
- Cualquier archivo en `frontend/src/`
- `frontend/package.json`
- `frontend/next.config.ts`
- `frontend/Dockerfile`
- Cualquier archivo de configuración de Next.js

### ⚠️ **Depende del contexto:**
- `frontend/README.md` - Puede ir en ambos o solo en frontend
- Scripts de deployment de frontend - Generalmente en `crypto-2.0/scripts/`

## 🚨 Problemas Comunes

### "Hice cambios pero no aparecen en GitHub"
- **Si cambiaste backend/scripts/workflows**: Verifica que hiciste commit en `crypto-2.0`
- **Si cambiaste frontend/src**: Verifica que hiciste commit en el repo `frontend`

### "Los cambios no se reflejan en AWS"
- Verifica que pusheaste en AMBOS repositorios
- Verifica que el workflow de deployment se ejecutó
- O sincroniza manualmente con `rsync`

## 💡 Recomendación Final

**Para simplificar**, considera unificar todo en `crypto-2.0`. Esto hará que:
- ✅ Todo esté en un solo lugar
- ✅ Deployment sea más simple
- ✅ Menos confusión sobre dónde van los archivos
- ✅ Historial unificado del proyecto

¿Quieres que te ayude a unificar los repositorios?








# ¿Qué Hay en el Directorio `frontend/` de crypto-2.0?

## 📁 Estructura del Directorio

El directorio `frontend/` dentro de `crypto-2.0` contiene **TODO el código del frontend**, pero:

### ⚠️ **IMPORTANTE:**
- `frontend/` tiene su **propio repositorio git** (`.git/`)
- El repositorio `crypto-2.0` **NO trackea** los archivos dentro de `frontend/`
- Solo hay una **referencia** a `frontend` en `crypto-2.0`, pero no los archivos reales

## 📦 Contenido del Directorio `frontend/`

```
frontend/
├── .git/                    # ⚠️ Repositorio git independiente
├── src/                     # ✅ Código fuente Next.js/TypeScript
│   ├── app/                 #   Páginas y componentes de Next.js
│   ├── components/          #   Componentes React
│   └── utils/               #   Utilidades
├── public/                   # ✅ Archivos estáticos
├── package.json             # ✅ Dependencias Node.js
├── next.config.ts           # ✅ Configuración Next.js
├── Dockerfile               # ✅ Docker para producción
├── Dockerfile.dev           # ✅ Docker para desarrollo
├── README.md                # ✅ Documentación
└── ... (otros archivos de configuración)
```

## 🔍 ¿Qué Está Trackeado en Cada Repositorio?

### En `crypto-2.0`:
- ❌ **NO** trackea archivos dentro de `frontend/`
- ✅ Solo tiene una referencia al directorio `frontend`
- ✅ Trackea: `backend/`, `scripts/`, `.github/`, `docker-compose.yml`, etc.

### En `frontend` (repo separado):
- ✅ **SÍ** trackea todos los archivos dentro de `frontend/`
- ✅ Todo el código Next.js
- ✅ Configuración y Dockerfiles
- ✅ Documentación del frontend

## 🎯 ¿Por Qué Esta Configuración?

Esta es una configuración de **repositorio anidado** (nested repository):
- `frontend/` es un repositorio git independiente
- Está físicamente dentro del directorio de `crypto-2.0`
- Pero git de `crypto-2.0` lo ignora porque detecta el `.git/` dentro

## 📝 Estado Actual

### En el repositorio `frontend`:
```
Cambios sin commitear:
  M src/app/page.tsx
  ?? public/clean-storage.js
```

### En el repositorio `crypto-2.0`:
```
Cambios sin commitear:
  m frontend  (referencia al directorio, no los archivos)
```

## 🔄 Flujo de Trabajo

### Cuando trabajas en Frontend:
```bash
cd /Users/carloscruz/automated-trading-platform/frontend
# Hacer cambios en src/, public/, etc.
git add .
git commit -m "tus cambios"
git push origin main  # Push al repo 'frontend'
```

### Cuando trabajas en Backend/Config:
```bash
cd /Users/carloscruz/automated-trading-platform
# Hacer cambios en backend/, scripts/, etc.
git add .
git commit -m "tus cambios"
git push origin main  # Push al repo 'crypto-2.0'
```

## ⚠️ Problemas Comunes

### "Hice cambios en frontend pero no aparecen en GitHub"
- **Solución**: Asegúrate de hacer commit en el repo `frontend`, no en `crypto-2.0`
- Verifica que estás en: `cd frontend` antes de `git add/commit/push`

### "Los cambios no se reflejan en AWS"
- **Solución**: 
  1. Push en el repo `frontend`
  2. El workflow de deploy sincroniza `frontend/` a AWS
  3. O sincroniza manualmente con `rsync`

## 💡 Recomendación

Para evitar confusión, considera:
1. **Agregar `frontend/` a `.gitignore` de `crypto-2.0`** (aunque git ya lo ignora automáticamente)
2. **Documentar claramente** que frontend es un repo separado
3. **Usar scripts helper** para deployment que manejen ambos repos

## 📋 Checklist de Archivos

### ✅ **Va al repo `frontend`:**
- Cualquier cambio en `frontend/src/`
- Cambios en `frontend/package.json`
- Cambios en `frontend/next.config.ts`
- Cambios en `frontend/Dockerfile`
- Cualquier archivo dentro de `frontend/`

### ✅ **Va al repo `crypto-2.0`:**
- Cambios en `backend/`
- Cambios en `scripts/`
- Cambios en `.github/workflows/`
- Cambios en `docker-compose.yml`
- Cambios fuera del directorio `frontend/`








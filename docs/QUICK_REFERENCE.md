# 🚀 Guía Rápida: ¿Dónde Va Cada Archivo?

## ✅ **Va a `crypto-2.0` (repo principal):**
- `backend/` - Todo el código Python
- `scripts/` - Scripts de deployment
- `.github/workflows/` - GitHub Actions
- `docker-compose.yml` - Configuración Docker
- `docs/` - Documentación
- Archivos de configuración en la raíz

**Comando:**
```bash
cd /Users/carloscruz/crypto-2.0
git add .
git commit -m "tus cambios"
git push origin main
```

## ✅ **Va a `frontend` (repo separado):**
- `frontend/src/` - Código React/Next.js
- `frontend/package.json` - Dependencias
- `frontend/next.config.ts` - Configuración Next.js
- `frontend/Dockerfile` - Docker del frontend

**Comando:**
```bash
cd /Users/carloscruz/crypto-2.0/frontend
git add .
git commit -m "tus cambios"
git push origin main
```

## ⚠️ **IMPORTANTE:**
Si cambias algo en `frontend/`, necesitas hacer commit en el repo `frontend`.
Si cambias algo fuera de `frontend/`, necesitas hacer commit en el repo `crypto-2.0`.

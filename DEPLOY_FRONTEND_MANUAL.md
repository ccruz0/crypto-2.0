# 📦 Manual Frontend Deployment - LIVE_TRADING Feature

## Archivos que necesitan ser desplegados:

1. `frontend/src/app/page.tsx` - Contiene el botón LIVE_TRADING en todas las secciones
2. `frontend/src/lib/api.ts` - Contiene las funciones `toggleLiveTrading()` y `getLiveTradingStatus()`

## Pasos para desplegar:

### Opción 1: Si el frontend está en el mismo servidor que el backend (175.41.189.249)

```bash
# 1. Copiar archivos al servidor
rsync -avz -e "ssh -i ~/.ssh/id_rsa" \
  frontend/src/app/page.tsx \
  frontend/src/lib/api.ts \
  ubuntu@175.41.189.249:~/automated-trading-platform/frontend/src/

# 2. Conectar al servidor
ssh -i ~/.ssh/id_rsa ubuntu@175.41.189.249

# 3. Copiar archivos al contenedor Docker y reiniciar
cd ~/automated-trading-platform
CONTAINER_NAME=$(docker ps --filter "name=frontend" --format "{{.Names}}" | head -1)
if [ -n "$CONTAINER_NAME" ]; then
  docker cp frontend/src/app/page.tsx $CONTAINER_NAME:/app/src/app/page.tsx
  docker cp frontend/src/lib/api.ts $CONTAINER_NAME:/app/src/lib/api.ts
  docker-compose restart frontend
  echo "✅ Frontend actualizado"
else
  echo "❌ Contenedor frontend no encontrado"
  docker ps
fi
```

### Opción 2: Si el frontend está en servidor separado (54.254.150.31)

```bash
# 1. Copiar archivos al servidor
rsync -avz -e "ssh -i ~/.ssh/id_rsa" \
  frontend/src/app/page.tsx \
  frontend/src/lib/api.ts \
  ubuntu@54.254.150.31:/home/ubuntu/automated-trading-platform/frontend/src/

# 2. Conectar al servidor
ssh -i ~/.ssh/id_rsa ubuntu@54.254.150.31

# 3. Copiar archivos al contenedor Docker y reiniciar
cd /home/ubuntu/automated-trading-platform
CONTAINER_NAME=$(docker ps --filter "name=frontend" --format "{{.Names}}" | head -1)
if [ -n "$CONTAINER_NAME" ]; then
  docker cp frontend/src/app/page.tsx $CONTAINER_NAME:/app/src/app/page.tsx
  docker cp frontend/src/lib/api.ts $CONTAINER_NAME:/app/src/lib/api.ts
  docker-compose restart frontend
  echo "✅ Frontend actualizado"
else
  echo "❌ Contenedor frontend no encontrado"
  docker ps
fi
```

## Verificación:

Después del deployment, verifica que el botón aparezca:

1. Abre el dashboard en el navegador
2. Deberías ver el botón "🟢 LIVE" o "🔴 DRY RUN" junto a "🟢 Bot Activo" en:
   - Portfolio
   - Watchlist
   - Open Orders
   - Executed Orders

## Si el frontend usa Next.js build:

Si el frontend necesita rebuild (no solo copiar archivos), ejecuta:

```bash
# En el servidor del frontend
cd /home/ubuntu/automated-trading-platform
docker-compose exec frontend npm run build
docker-compose restart frontend
```

## Troubleshooting:

- Si el botón no aparece, verifica los logs del frontend:
  ```bash
  docker logs <frontend-container-name> --tail 50
  ```

- Verifica que los archivos se copiaron correctamente:
  ```bash
  docker exec <frontend-container-name> ls -la /app/src/app/page.tsx
  docker exec <frontend-container-name> ls -la /app/src/lib/api.ts
  ```


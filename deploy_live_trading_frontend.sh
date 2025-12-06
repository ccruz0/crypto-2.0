#!/bin/bash

# Script para desplegar los cambios de LIVE_TRADING en el frontend
# Ejecutar cuando tengas acceso al servidor

# Configuration
EC2_HOST="${EC2_HOST:-54.254.150.31}"
EC2_USER="${EC2_USER:-ubuntu}"
# Unified SSH
. ./scripts/ssh_key.sh 2>/dev/null || source ./scripts/ssh_key.sh

echo "🚀 Deploying LIVE_TRADING frontend updates..."

# Verificar que los archivos existen
if [ ! -f "frontend/src/app/page.tsx" ]; then
    echo "❌ Error: frontend/src/app/page.tsx not found"
    exit 1
fi

if [ ! -f "frontend/src/lib/api.ts" ]; then
    echo "❌ Error: frontend/src/lib/api.ts not found"
    exit 1
fi

# Copiar archivos al servidor
echo "📦 Copying files to server..."
rsync_cmd \
  frontend/src/app/page.tsx \
  frontend/src/lib/api.ts \
  $EC2_USER@$EC2_HOST:/home/ubuntu/automated-trading-platform/frontend/src/ 2>&1

if [ $? -ne 0 ]; then
    echo "⚠️  Connection failed. Trying alternative method..."
    echo "📝 Manual deployment steps:"
    echo "   1. Copy frontend/src/app/page.tsx to server"
    echo "   2. Copy frontend/src/lib/api.ts to server"
    echo "   3. Copy files into Docker container:"
    echo "      docker cp frontend/src/app/page.tsx <container>:/app/src/app/page.tsx"
    echo "      docker cp frontend/src/lib/api.ts <container>:/app/src/lib/api.ts"
    echo "   4. Restart frontend: docker-compose restart frontend"
    exit 1
fi

# Copiar archivos al contenedor Docker y reiniciar
echo "🐳 Copying files to Docker container..."
ssh_cmd $EC2_USER@$EC2_HOST << 'EOF'
cd /home/ubuntu/automated-trading-platform

# Find the correct container name
CONTAINER_NAME=$(docker ps --filter "name=frontend" --format "{{.Names}}" | head -1)

if [ -n "$CONTAINER_NAME" ]; then
  echo "Found container: $CONTAINER_NAME"
  docker cp frontend/src/app/page.tsx $CONTAINER_NAME:/app/src/app/page.tsx
  docker cp frontend/src/lib/api.ts $CONTAINER_NAME:/app/src/lib/api.ts
  echo "✅ Files copied to container"
  
  echo "🔄 Restarting frontend..."
  docker-compose restart frontend
  
  sleep 3
  echo "📋 Recent logs:"
  docker logs --tail 20 $CONTAINER_NAME
else
  echo "❌ Frontend container not found"
  echo "Available containers:"
  docker ps --format "{{.Names}}"
fi
EOF

echo ""
echo "✅ Deployment complete!"
echo ""
echo "The LIVE_TRADING button should now appear in all dashboard sections:"
echo "  - Portfolio"
echo "  - Watchlist"
echo "  - Open Orders"
echo "  - Executed Orders"


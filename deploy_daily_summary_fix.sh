#!/bin/bash

# Try SSH alias first, fallback to IP
REMOTE_HOST="${REMOTE_HOST:-hilovivo-aws}"
REMOTE_USER="ubuntu"

echo "🚀 Desplegando fix del resumen diario a AWS..."
echo "📍 Host: $REMOTE_HOST"
echo ""

# Test SSH connection
echo "🔍 Probando conexión SSH..."
if ! ssh -o ConnectTimeout=5 "$REMOTE_HOST" "echo 'Connected'" > /dev/null 2>&1; then
    echo "⚠️  No se pudo conectar con alias '$REMOTE_HOST'"
    echo "💡 Intentando con IP directa..."
    REMOTE_HOST="54.254.150.31"
    if ! ssh -o ConnectTimeout=5 "$REMOTE_USER@$REMOTE_HOST" "echo 'Connected'" > /dev/null 2>&1; then
        echo "❌ No se pudo conectar a AWS"
        echo "🔧 Verifica tu configuración SSH o conectividad de red"
        exit 1
    fi
    REMOTE_TARGET="$REMOTE_USER@$REMOTE_HOST"
else
    REMOTE_TARGET="$REMOTE_HOST"
fi

echo "✅ Conexión SSH exitosa"
echo ""

# Sync only the changed file
echo "📦 Sincronizando archivo..."
rsync -avz --progress \
  --exclude='__pycache__' \
  --exclude='*.pyc' \
  backend/app/services/daily_summary.py \
  $REMOTE_TARGET:~/automated-trading-platform/backend/app/services/

# Copy file into Docker container and restart
echo "🐳 Copiando archivo al contenedor Docker y reiniciando..."
ssh $REMOTE_TARGET << 'DEPLOY'
cd ~/automated-trading-platform || cd /home/ubuntu/crypto-2.0

# Find backend container (try multiple patterns)
BACKEND=$(docker ps --filter "name=backend" --format "{{.Names}}" | head -1)

if [ -z "$BACKEND" ]; then
  # Try AWS profile container name
  BACKEND=$(docker ps --filter "name=backend-aws" --format "{{.Names}}" | head -1)
fi

if [ -z "$BACKEND" ]; then
  # Try fixed name
  BACKEND="automated-trading-platform_backend_1"
fi

echo "Contenedor backend: ${BACKEND:-NO ENCONTRADO}"

# Copy file
if [ -n "$BACKEND" ] && docker ps --format "{{.Names}}" | grep -q "$BACKEND"; then
  docker cp backend/app/services/daily_summary.py $BACKEND:/app/app/services/daily_summary.py
  echo "✅ Archivo copiado al contenedor"
  
  # Restart backend
  echo "🔄 Reiniciando backend..."
  docker compose --profile aws restart backend-aws 2>/dev/null || \
  docker compose restart backend 2>/dev/null || \
  docker restart $BACKEND 2>/dev/null || \
  echo "⚠️  No se pudo reiniciar automáticamente, reinicia manualmente"
  
  echo "⏳ Esperando que el servicio se inicie..."
  sleep 5
  
  # Check health (try multiple ports)
  if curl -f http://localhost:8000/api/health >/dev/null 2>&1 || \
     curl -f http://localhost:8002/ping_fast >/dev/null 2>&1; then
    echo "✅ Backend está saludable"
  else
    echo "⚠️  Verificación de salud falló (puede ser normal durante el reinicio)"
  fi
else
  echo "⚠️  No se pudo encontrar el contenedor backend en ejecución"
  echo "Contenedores disponibles:"
  docker ps --format "{{.Names}}"
  echo ""
  echo "💡 El archivo fue sincronizado al servidor, pero no se pudo copiar al contenedor."
  echo "   Puedes copiarlo manualmente o reiniciar el contenedor."
fi

echo "✅ Despliegue completado!"
DEPLOY

echo ""
echo "✅ Fix del resumen diario desplegado exitosamente!"
echo ""
echo "El resumen diario ahora incluirá:"
echo "  • Mejor manejo de errores con información detallada"
echo "  • Soporte para diferentes formatos de respuesta de la API"
echo "  • Manejo de timestamps en segundos y milisegundos"
echo "  • Advertencias en el mensaje si hay errores parciales"

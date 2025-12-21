#!/bin/bash
# Script para aplicar el fix de SL directamente en el servidor AWS
# Ejecutar este script en el servidor: bash apply_sl_fix_on_server.sh

set -e

echo "🚀 Aplicando fix de visualización de SL..."
echo ""

cd ~/automated-trading-platform || cd /home/ubuntu/automated-trading-platform

# Verificar que los archivos existen
if [ ! -f "backend/app/api/routes_orders.py" ]; then
    echo "❌ Error: No se encontró backend/app/api/routes_orders.py"
    echo "   Asegúrate de que los cambios se hayan sincronizado al servidor"
    exit 1
fi

if [ ! -f "frontend/src/lib/api.ts" ]; then
    echo "❌ Error: No se encontró frontend/src/lib/api.ts"
    echo "   Asegúrate de que los cambios se hayan sincronizado al servidor"
    exit 1
fi

if [ ! -f "frontend/src/app/page.tsx" ]; then
    echo "❌ Error: No se encontró frontend/src/app/page.tsx"
    echo "   Asegúrate de que los cambios se hayan sincronizado al servidor"
    exit 1
fi

echo "✅ Archivos encontrados"
echo ""

# Reiniciar backend
echo "🔄 Reiniciando backend..."
if docker compose --profile aws ps backend 2>/dev/null | grep -q "Up"; then
    echo "📦 Usando Docker Compose"
    docker compose --profile aws restart backend
    
    echo "⏳ Esperando 5 segundos..."
    sleep 5
    
    echo ""
    echo "📊 Estado del backend:"
    docker compose --profile aws ps backend
    
    echo ""
    echo "📋 Logs recientes:"
    docker compose --profile aws logs --tail=30 backend
elif pgrep -f "uvicorn app.main:app" > /dev/null; then
    echo "🐍 Usando proceso Python directo"
    echo "🛑 Deteniendo backend existente..."
    pkill -f "uvicorn app.main:app"
    sleep 2
    
    cd backend
    if [ -d "venv" ]; then
        source venv/bin/activate
    fi
    
    echo "🚀 Iniciando backend..."
    nohup python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 > backend.log 2>&1 &
    
    sleep 3
    echo "✅ Backend reiniciado"
    echo ""
    echo "📋 Logs recientes:"
    tail -30 backend.log
else
    echo "⚠️  No se encontró proceso backend en ejecución"
    echo ""
    echo "Contenedores Docker disponibles:"
    docker compose --profile aws ps 2>/dev/null || docker ps 2>/dev/null || echo "   Docker no disponible"
    echo ""
    echo "Procesos Python:"
    ps aux | grep uvicorn | grep -v grep || echo "   No se encontraron procesos uvicorn"
fi

echo ""
echo "🧪 Verificando salud del backend..."
sleep 3
if curl -f --connect-timeout 5 http://localhost:8002/health >/dev/null 2>&1 || curl -f --connect-timeout 5 http://localhost:8000/api/health >/dev/null 2>&1; then
    echo "✅ Backend está saludable y respondiendo"
else
    echo "⚠️  Verificación de salud falló - puede necesitar más tiempo para iniciar"
fi

echo ""
echo "✅ Fix aplicado!"
echo ""
echo "📝 Próximos pasos:"
echo "1. Si el frontend está en Docker, reinícialo también:"
echo "   docker compose --profile aws restart frontend"
echo "2. Recarga el frontend en el navegador (F5 o Cmd+R)"
echo "3. Verifica que los valores de SL aparezcan en la tabla de Holdings"








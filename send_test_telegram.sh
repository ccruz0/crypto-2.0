#!/bin/bash
# Script para enviar mensaje de prueba a Telegram desde AWS

echo "=========================================================="
echo "📤 ENVIANDO MENSAJE DE PRUEBA A TELEGRAM"
echo "=========================================================="
echo ""

# Verificar si estamos en el directorio correcto
if [ ! -f "docker-compose.yml" ]; then
    echo "❌ Error: No se encontró docker-compose.yml"
    echo "   Ejecuta este script desde el directorio raíz del proyecto"
    exit 1
fi

# Verificar si el backend está corriendo
if ! docker compose ps backend | grep -q "running"; then
    echo "⚠️  El servicio backend no está corriendo"
    echo "   Iniciando backend..."
    docker compose up -d backend
    sleep 5
fi

echo "🚀 Ejecutando script de prueba..."
echo ""

# Ejecutar el script
docker compose exec -T backend python scripts/send_test_message.py

exit_code=$?

echo ""
if [ $exit_code -eq 0 ]; then
    echo "✅ Script ejecutado exitosamente"
    echo "💡 Verifica tu chat de Telegram para confirmar la recepción"
else
    echo "❌ El script terminó con errores"
    echo "📋 Revisa la salida arriba para más detalles"
fi

exit $exit_code












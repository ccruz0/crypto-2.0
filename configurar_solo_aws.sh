#!/bin/bash
# Script para configurar el sistema para usar solo el servicio backend-aws
# Esto evita notificaciones duplicadas de Telegram

set -e

echo "🚀 Configurando sistema para usar solo backend-aws..."
echo ""

# 1. Detener servicios locales (si están corriendo)
echo "📦 Deteniendo servicios locales (perfil 'local')..."
docker compose --profile local down 2>/dev/null || echo "   (No hay servicios locales corriendo)"

# 2. Verificar que .env.aws existe
if [ ! -f ".env.aws" ]; then
    echo "⚠️  ADVERTENCIA: .env.aws no encontrado"
    echo "   Asegúrate de que existe y contiene:"
    echo "   - TELEGRAM_BOT_TOKEN=..."
    echo "   - TELEGRAM_CHAT_ID=..."
    echo ""
fi

# 3. Iniciar servicios AWS
echo "☁️  Iniciando servicios AWS (perfil 'aws')..."
docker compose --profile aws up -d

# 4. Esperar a que los servicios estén listos
echo ""
echo "⏳ Esperando a que los servicios estén listos..."
sleep 10

# 5. Verificar estado
echo ""
echo "📊 Estado de los servicios:"
docker compose --profile aws ps

# 6. Verificar configuración de Telegram en backend-aws
echo ""
echo "🔍 Verificando configuración de Telegram en backend-aws..."
docker compose --profile aws exec backend-aws env 2>/dev/null | grep -E "RUNTIME_ORIGIN|TELEGRAM|RUN_TELEGRAM" | sort || echo "   (Servicio aún no está listo, espera unos segundos más)"

# 7. Verificar que el fix está aplicado
echo ""
echo "✅ Verificando que el fix está aplicado..."
if docker compose --profile aws exec backend-aws python3 -c "from app.services.telegram_notifier import TelegramNotifier; import inspect; src = inspect.getsource(TelegramNotifier.send_sl_tp_orders); print('✅ Fix aplicado' if 'origin=get_runtime_origin()' in src or 'origin=origin' in src else '❌ Fix NO encontrado')" 2>/dev/null; then
    echo "   ✅ El fix está aplicado en el código"
else
    echo "   ⚠️  No se pudo verificar el fix (el servicio puede estar iniciando)"
fi

echo ""
echo "✅ Configuración completada!"
echo ""
echo "📝 Próximos pasos:"
echo "   1. Verifica que backend-aws esté corriendo:"
echo "      docker compose --profile aws ps backend-aws"
echo ""
echo "   2. Monitorea los logs para verificar notificaciones:"
echo "      docker compose --profile aws logs -f backend-aws | grep -i 'sl/tp\\|telegram'"
echo ""
echo "   3. La próxima vez que se creen órdenes SL/TP, recibirás la notificación en Telegram"
echo ""







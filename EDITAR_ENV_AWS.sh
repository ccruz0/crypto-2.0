#!/bin/bash
# Script para editar .env.local en AWS
# Usage: ./EDITAR_ENV_AWS.sh

AWS_SERVER="ubuntu@47.130.143.159"
ENV_FILE="~/automated-trading-platform/.env.local"

echo "============================================================"
echo "📝 EDITAR .env.local EN AWS"
echo "============================================================"
echo ""
echo "Servidor: $AWS_SERVER"
echo "Archivo: $ENV_FILE"
echo ""
echo "Opciones:"
echo "1. Ver contenido completo"
echo "2. Editar con nano (interactivo)"
echo "3. Editar con vim (interactivo)"
echo "4. Ver solo configuración de Crypto.com"
echo ""
read -p "Selecciona opción (1-4): " opcion

case $opcion in
    1)
        echo ""
        echo "📄 Contenido completo:"
        echo "============================================================"
        ssh $AWS_SERVER "cat $ENV_FILE"
        ;;
    2)
        echo ""
        echo "📝 Abriendo con nano..."
        ssh -t $AWS_SERVER "nano $ENV_FILE"
        ;;
    3)
        echo ""
        echo "📝 Abriendo con vim..."
        ssh -t $AWS_SERVER "vim $ENV_FILE"
        ;;
    4)
        echo ""
        echo "🔑 Configuración de Crypto.com:"
        echo "============================================================"
        ssh $AWS_SERVER "grep -E 'EXCHANGE_CUSTOM|CRYPTO|LIVE_TRADING|USE_CRYPTO_PROXY' $ENV_FILE"
        ;;
    *)
        echo "Opción inválida"
        exit 1
        ;;
esac

echo ""
echo "============================================================"
echo "💡 Después de editar, reinicia el backend:"
echo "   ssh $AWS_SERVER 'cd ~/automated-trading-platform && docker compose restart backend-aws'"
echo "============================================================"


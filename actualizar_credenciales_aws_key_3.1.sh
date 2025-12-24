#!/bin/bash
# Script para actualizar credenciales a AWS KEY 3.1 en todos los archivos
# Usage: ./actualizar_credenciales_aws_key_3.1.sh

set -e

AWS_SERVER="ubuntu@47.130.143.159"
API_KEY="raHZAk1MDkAWviDpcBxAWU"

echo "============================================================"
echo "🔑 ACTUALIZAR CREDENCIALES A AWS KEY 3.1"
echo "============================================================"
echo ""
echo "API Key: $API_KEY"
echo ""

# Solicitar Secret Key de forma segura
read -sp "Ingresa el Secret Key de AWS KEY 3.1: " API_SECRET
echo ""

if [ -z "$API_SECRET" ]; then
    echo "❌ ERROR: Secret Key no puede estar vacío"
    exit 1
fi

echo ""
echo "📝 Actualizando archivos..."

# 1. Actualizar .env.local en AWS
echo ""
echo "1️⃣  Actualizando .env.local en AWS..."
ssh $AWS_SERVER "cd ~/automated-trading-platform && \
    sed -i.bak 's/^EXCHANGE_CUSTOM_API_KEY=.*/EXCHANGE_CUSTOM_API_KEY=$API_KEY/' .env.local && \
    sed -i.bak 's/^EXCHANGE_CUSTOM_API_SECRET=.*/EXCHANGE_CUSTOM_API_SECRET=$API_SECRET/' .env.local && \
    echo '✅ .env.local actualizado en AWS'"

# 2. Actualizar .env.local local (si existe)
if [ -f ".env.local" ]; then
    echo ""
    echo "2️⃣  Actualizando .env.local local..."
    cp .env.local .env.local.bak.$(date +%Y%m%d_%H%M%S)
    sed -i.bak "s/^EXCHANGE_CUSTOM_API_KEY=.*/EXCHANGE_CUSTOM_API_KEY=$API_KEY/" .env.local
    sed -i.bak "s/^EXCHANGE_CUSTOM_API_SECRET=.*/EXCHANGE_CUSTOM_API_SECRET=$API_SECRET/" .env.local
    echo "✅ .env.local local actualizado (backup creado)"
fi

# 3. Actualizar otros archivos .env que puedan tener credenciales
echo ""
echo "3️⃣  Buscando otros archivos .env con credenciales de Crypto.com..."

# Buscar y actualizar archivos .env.aws si existen
for env_file in .env.aws .env.aws.bak .env.aws.tmp; do
    if [ -f "$env_file" ]; then
        echo "   Actualizando $env_file..."
        cp "$env_file" "${env_file}.bak.$(date +%Y%m%d_%H%M%S)"
        if grep -q "EXCHANGE_CUSTOM_API_KEY" "$env_file"; then
            sed -i.bak "s/^EXCHANGE_CUSTOM_API_KEY=.*/EXCHANGE_CUSTOM_API_KEY=$API_KEY/" "$env_file"
            sed -i.bak "s/^EXCHANGE_CUSTOM_API_SECRET=.*/EXCHANGE_CUSTOM_API_SECRET=$API_SECRET/" "$env_file"
            echo "   ✅ $env_file actualizado"
        else
            # Agregar si no existe
            echo "" >> "$env_file"
            echo "# Crypto.com Exchange Configuration" >> "$env_file"
            echo "EXCHANGE_CUSTOM_API_KEY=$API_KEY" >> "$env_file"
            echo "EXCHANGE_CUSTOM_API_SECRET=$API_SECRET" >> "$env_file"
            echo "   ✅ Credenciales agregadas a $env_file"
        fi
    fi
done

# 4. Actualizar archivos Python que tengan credenciales hardcodeadas (opcional)
echo ""
echo "4️⃣  Buscando archivos Python con credenciales hardcodeadas..."
python_files=(
    "aws_trading_server.py"
    "aws_ip_server.py"
    "aws_proxy_server.py"
    "local_working_server.py"
)

for py_file in "${python_files[@]}"; do
    if [ -f "$py_file" ] && grep -q "z3HWF8m292zJKABkzfXWvQ" "$py_file"; then
        echo "   ⚠️  $py_file tiene credenciales hardcodeadas"
        echo "   💡 Considera actualizar manualmente o usar variables de entorno"
    fi
done

echo ""
echo "============================================================"
echo "✅ ACTUALIZACIÓN COMPLETA"
echo "============================================================"
echo ""
echo "📋 Archivos actualizados:"
echo "   ✅ .env.local en AWS"
if [ -f ".env.local" ]; then
    echo "   ✅ .env.local local"
fi
echo ""
echo "🔄 Próximos pasos:"
echo "   1. Reiniciar backend en AWS:"
echo "      ssh $AWS_SERVER 'cd ~/automated-trading-platform && docker compose restart backend-aws'"
echo ""
echo "   2. Verificar que funciona:"
echo "      ssh $AWS_SERVER 'cd ~/automated-trading-platform/backend && python3 scripts/deep_auth_diagnostic.py'"
echo ""
echo "============================================================"


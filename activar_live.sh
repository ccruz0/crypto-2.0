#!/bin/bash
# Script para activar LIVE TRADING

echo "🚀 Activando LIVE TRADING..."
echo ""

# Verificar que .env.local existe
if [ ! -f .env.local ]; then
    echo "❌ Archivo .env.local no encontrado"
    echo "📝 Creando archivo .env.local..."
    touch .env.local
fi

# Leer .env.local y actualizar LIVE_TRADING
if grep -q "^LIVE_TRADING=" .env.local; then
    # Actualizar línea existente
    sed -i.bak 's/^LIVE_TRADING=.*/LIVE_TRADING=true/' .env.local
    echo "✅ Actualizado LIVE_TRADING=true en .env.local"
else
    # Añadir nueva línea
    echo "LIVE_TRADING=true" >> .env.local
    echo "✅ Añadido LIVE_TRADING=true a .env.local"
fi

# Asegurar que USE_CRYPTO_PROXY=false
if grep -q "^USE_CRYPTO_PROXY=" .env.local; then
    sed -i.bak 's/^USE_CRYPTO_PROXY=.*/USE_CRYPTO_PROXY=false/' .env.local
else
    echo "USE_CRYPTO_PROXY=false" >> .env.local
fi

echo ""
echo "⚠️  IMPORTANTE: Tu IP pública es:"
curl -s https://api.ipify.org
echo ""
echo ""
echo "📋 Checklist:"
echo "   ✅ LIVE_TRADING=true configurado"
echo "   ⚠️  Verifica que tu IP esté en la whitelist de Crypto.com Exchange"
echo ""
echo "🔄 Reiniciando backend..."
docker compose restart backend
echo ""
echo "✅ Backend reiniciado. Espera 10 segundos y verifica:"
echo "   docker compose exec backend python scripts/setup_live_trading.py"


#!/bin/bash

# Script para configurar la conexión a Crypto.com Exchange
# Este script te ayudará a configurar las variables de entorno necesarias

echo "============================================================"
echo "🔌 Configuración de Conexión a Crypto.com Exchange"
echo "============================================================"
echo ""

# Verificar si existe .env.local
if [ ! -f "../.env.local" ]; then
    echo "📝 Creando archivo .env.local..."
    touch ../.env.local
fi

echo "📋 Por favor, proporciona la siguiente información:"
echo ""

# Preguntar por el método de conexión
echo "¿Qué método de conexión quieres usar?"
echo "1) Conexión directa (requiere IP whitelisted)"
echo "2) Proxy (requiere proxy corriendo en puerto 9000)"
echo "3) Modo Dry-Run (datos simulados para testing)"
read -p "Opción (1-3): " connection_method

case $connection_method in
    1)
        echo ""
        echo "✅ Configurando conexión directa..."
        
        read -p "📝 API Key de Crypto.com Exchange: " api_key
        read -p "📝 API Secret de Crypto.com Exchange: " api_secret
        
        # Actualizar o agregar variables al .env.local
        grep -q "USE_CRYPTO_PROXY" ../.env.local && \
            sed -i '' "s/USE_CRYPTO_PROXY=.*/USE_CRYPTO_PROXY=false/" ../.env.local || \
            echo "USE_CRYPTO_PROXY=false" >> ../.env.local
        
        grep -q "LIVE_TRADING" ../.env.local && \
            sed -i '' "s/LIVE_TRADING=.*/LIVE_TRADING=true/" ../.env.local || \
            echo "LIVE_TRADING=true" >> ../.env.local
        
        grep -q "EXCHANGE_CUSTOM_API_KEY" ../.env.local && \
            sed -i '' "s/EXCHANGE_CUSTOM_API_KEY=.*/EXCHANGE_CUSTOM_API_KEY=${api_key}/" ../.env.local || \
            echo "EXCHANGE_CUSTOM_API_KEY=${api_key}" >> ../.env.local
        
        grep -q "EXCHANGE_CUSTOM_API_SECRET" ../.env.local && \
            sed -i '' "s/EXCHANGE_CUSTOM_API_SECRET=.*/EXCHANGE_CUSTOM_API_SECRET=${api_secret}/" ../.env.local || \
            echo "EXCHANGE_CUSTOM_API_SECRET=${api_secret}" >> ../.env.local
        
        echo ""
        echo "✅ Configuración guardada en .env.local"
        echo ""
        echo "⚠️  IMPORTANTE: Asegúrate de que tu IP está whitelisted en Crypto.com Exchange"
        echo "   Obtén tu IP pública: curl https://api.ipify.org"
        ;;
    2)
        echo ""
        echo "✅ Configurando conexión a través de proxy..."
        
        read -p "📝 URL del proxy (default: http://127.0.0.1:9000): " proxy_url
        proxy_url=${proxy_url:-http://127.0.0.1:9000}
        
        read -p "📝 Token del proxy: " proxy_token
        
        grep -q "USE_CRYPTO_PROXY" ../.env.local && \
            sed -i '' "s/USE_CRYPTO_PROXY=.*/USE_CRYPTO_PROXY=true/" ../.env.local || \
            echo "USE_CRYPTO_PROXY=true" >> ../.env.local
        
        grep -q "CRYPTO_PROXY_URL" ../.env.local && \
            sed -i '' "s|CRYPTO_PROXY_URL=.*|CRYPTO_PROXY_URL=${proxy_url}|" ../.env.local || \
            echo "CRYPTO_PROXY_URL=${proxy_url}" >> ../.env.local
        
        grep -q "CRYPTO_PROXY_TOKEN" ../.env.local && \
            sed -i '' "s/CRYPTO_PROXY_TOKEN=.*/CRYPTO_PROXY_TOKEN=${proxy_token}/" ../.env.local || \
            echo "CRYPTO_PROXY_TOKEN=${proxy_token}" >> ../.env.local
        
        grep -q "LIVE_TRADING" ../.env.local && \
            sed -i '' "s/LIVE_TRADING=.*/LIVE_TRADING=true/" ../.env.local || \
            echo "LIVE_TRADING=true" >> ../.env.local
        
        echo ""
        echo "✅ Configuración guardada en .env.local"
        echo ""
        echo "⚠️  IMPORTANTE: Asegúrate de que el proxy esté corriendo en ${proxy_url}"
        ;;
    3)
        echo ""
        echo "✅ Configurando modo Dry-Run..."
        
        grep -q "USE_CRYPTO_PROXY" ../.env.local && \
            sed -i '' "s/USE_CRYPTO_PROXY=.*/USE_CRYPTO_PROXY=false/" ../.env.local || \
            echo "USE_CRYPTO_PROXY=false" >> ../.env.local
        
        grep -q "LIVE_TRADING" ../.env.local && \
            sed -i '' "s/LIVE_TRADING=.*/LIVE_TRADING=false/" ../.env.local || \
            echo "LIVE_TRADING=false" >> ../.env.local
        
        echo ""
        echo "✅ Configuración guardada en .env.local"
        echo ""
        echo "ℹ️  Modo Dry-Run activado - Se usarán datos simulados"
        ;;
    *)
        echo "❌ Opción inválida"
        exit 1
        ;;
esac

echo ""
echo "============================================================"
echo "✅ Configuración completada"
echo "============================================================"
echo ""
echo "📋 Próximos pasos:"
echo "1. Reinicia el backend: docker compose restart backend"
echo "2. Prueba la conexión: docker compose exec backend python scripts/test_crypto_connection.py"
echo "3. Verifica los logs: docker compose logs -f backend"
echo ""


# Script para configurar la conexión a Crypto.com Exchange
# Este script te ayudará a configurar las variables de entorno necesarias

echo "============================================================"
echo "🔌 Configuración de Conexión a Crypto.com Exchange"
echo "============================================================"
echo ""

# Verificar si existe .env.local
if [ ! -f "../.env.local" ]; then
    echo "📝 Creando archivo .env.local..."
    touch ../.env.local
fi

echo "📋 Por favor, proporciona la siguiente información:"
echo ""

# Preguntar por el método de conexión
echo "¿Qué método de conexión quieres usar?"
echo "1) Conexión directa (requiere IP whitelisted)"
echo "2) Proxy (requiere proxy corriendo en puerto 9000)"
echo "3) Modo Dry-Run (datos simulados para testing)"
read -p "Opción (1-3): " connection_method

case $connection_method in
    1)
        echo ""
        echo "✅ Configurando conexión directa..."
        
        read -p "📝 API Key de Crypto.com Exchange: " api_key
        read -p "📝 API Secret de Crypto.com Exchange: " api_secret
        
        # Actualizar o agregar variables al .env.local
        grep -q "USE_CRYPTO_PROXY" ../.env.local && \
            sed -i '' "s/USE_CRYPTO_PROXY=.*/USE_CRYPTO_PROXY=false/" ../.env.local || \
            echo "USE_CRYPTO_PROXY=false" >> ../.env.local
        
        grep -q "LIVE_TRADING" ../.env.local && \
            sed -i '' "s/LIVE_TRADING=.*/LIVE_TRADING=true/" ../.env.local || \
            echo "LIVE_TRADING=true" >> ../.env.local
        
        grep -q "EXCHANGE_CUSTOM_API_KEY" ../.env.local && \
            sed -i '' "s/EXCHANGE_CUSTOM_API_KEY=.*/EXCHANGE_CUSTOM_API_KEY=${api_key}/" ../.env.local || \
            echo "EXCHANGE_CUSTOM_API_KEY=${api_key}" >> ../.env.local
        
        grep -q "EXCHANGE_CUSTOM_API_SECRET" ../.env.local && \
            sed -i '' "s/EXCHANGE_CUSTOM_API_SECRET=.*/EXCHANGE_CUSTOM_API_SECRET=${api_secret}/" ../.env.local || \
            echo "EXCHANGE_CUSTOM_API_SECRET=${api_secret}" >> ../.env.local
        
        echo ""
        echo "✅ Configuración guardada en .env.local"
        echo ""
        echo "⚠️  IMPORTANTE: Asegúrate de que tu IP está whitelisted en Crypto.com Exchange"
        echo "   Obtén tu IP pública: curl https://api.ipify.org"
        ;;
    2)
        echo ""
        echo "✅ Configurando conexión a través de proxy..."
        
        read -p "📝 URL del proxy (default: http://127.0.0.1:9000): " proxy_url
        proxy_url=${proxy_url:-http://127.0.0.1:9000}
        
        read -p "📝 Token del proxy: " proxy_token
        
        grep -q "USE_CRYPTO_PROXY" ../.env.local && \
            sed -i '' "s/USE_CRYPTO_PROXY=.*/USE_CRYPTO_PROXY=true/" ../.env.local || \
            echo "USE_CRYPTO_PROXY=true" >> ../.env.local
        
        grep -q "CRYPTO_PROXY_URL" ../.env.local && \
            sed -i '' "s|CRYPTO_PROXY_URL=.*|CRYPTO_PROXY_URL=${proxy_url}|" ../.env.local || \
            echo "CRYPTO_PROXY_URL=${proxy_url}" >> ../.env.local
        
        grep -q "CRYPTO_PROXY_TOKEN" ../.env.local && \
            sed -i '' "s/CRYPTO_PROXY_TOKEN=.*/CRYPTO_PROXY_TOKEN=${proxy_token}/" ../.env.local || \
            echo "CRYPTO_PROXY_TOKEN=${proxy_token}" >> ../.env.local
        
        grep -q "LIVE_TRADING" ../.env.local && \
            sed -i '' "s/LIVE_TRADING=.*/LIVE_TRADING=true/" ../.env.local || \
            echo "LIVE_TRADING=true" >> ../.env.local
        
        echo ""
        echo "✅ Configuración guardada en .env.local"
        echo ""
        echo "⚠️  IMPORTANTE: Asegúrate de que el proxy esté corriendo en ${proxy_url}"
        ;;
    3)
        echo ""
        echo "✅ Configurando modo Dry-Run..."
        
        grep -q "USE_CRYPTO_PROXY" ../.env.local && \
            sed -i '' "s/USE_CRYPTO_PROXY=.*/USE_CRYPTO_PROXY=false/" ../.env.local || \
            echo "USE_CRYPTO_PROXY=false" >> ../.env.local
        
        grep -q "LIVE_TRADING" ../.env.local && \
            sed -i '' "s/LIVE_TRADING=.*/LIVE_TRADING=false/" ../.env.local || \
            echo "LIVE_TRADING=false" >> ../.env.local
        
        echo ""
        echo "✅ Configuración guardada en .env.local"
        echo ""
        echo "ℹ️  Modo Dry-Run activado - Se usarán datos simulados"
        ;;
    *)
        echo "❌ Opción inválida"
        exit 1
        ;;
esac

echo ""
echo "============================================================"
echo "✅ Configuración completada"
echo "============================================================"
echo ""
echo "📋 Próximos pasos:"
echo "1. Reinicia el backend: docker compose restart backend"
echo "2. Prueba la conexión: docker compose exec backend python scripts/test_crypto_connection.py"
echo "3. Verifica los logs: docker compose logs -f backend"
echo ""


# Script para configurar la conexión a Crypto.com Exchange
# Este script te ayudará a configurar las variables de entorno necesarias

echo "============================================================"
echo "🔌 Configuración de Conexión a Crypto.com Exchange"
echo "============================================================"
echo ""

# Verificar si existe .env.local
if [ ! -f "../.env.local" ]; then
    echo "📝 Creando archivo .env.local..."
    touch ../.env.local
fi

echo "📋 Por favor, proporciona la siguiente información:"
echo ""

# Preguntar por el método de conexión
echo "¿Qué método de conexión quieres usar?"
echo "1) Conexión directa (requiere IP whitelisted)"
echo "2) Proxy (requiere proxy corriendo en puerto 9000)"
echo "3) Modo Dry-Run (datos simulados para testing)"
read -p "Opción (1-3): " connection_method

case $connection_method in
    1)
        echo ""
        echo "✅ Configurando conexión directa..."
        
        read -p "📝 API Key de Crypto.com Exchange: " api_key
        read -p "📝 API Secret de Crypto.com Exchange: " api_secret
        
        # Actualizar o agregar variables al .env.local
        grep -q "USE_CRYPTO_PROXY" ../.env.local && \
            sed -i '' "s/USE_CRYPTO_PROXY=.*/USE_CRYPTO_PROXY=false/" ../.env.local || \
            echo "USE_CRYPTO_PROXY=false" >> ../.env.local
        
        grep -q "LIVE_TRADING" ../.env.local && \
            sed -i '' "s/LIVE_TRADING=.*/LIVE_TRADING=true/" ../.env.local || \
            echo "LIVE_TRADING=true" >> ../.env.local
        
        grep -q "EXCHANGE_CUSTOM_API_KEY" ../.env.local && \
            sed -i '' "s/EXCHANGE_CUSTOM_API_KEY=.*/EXCHANGE_CUSTOM_API_KEY=${api_key}/" ../.env.local || \
            echo "EXCHANGE_CUSTOM_API_KEY=${api_key}" >> ../.env.local
        
        grep -q "EXCHANGE_CUSTOM_API_SECRET" ../.env.local && \
            sed -i '' "s/EXCHANGE_CUSTOM_API_SECRET=.*/EXCHANGE_CUSTOM_API_SECRET=${api_secret}/" ../.env.local || \
            echo "EXCHANGE_CUSTOM_API_SECRET=${api_secret}" >> ../.env.local
        
        echo ""
        echo "✅ Configuración guardada en .env.local"
        echo ""
        echo "⚠️  IMPORTANTE: Asegúrate de que tu IP está whitelisted en Crypto.com Exchange"
        echo "   Obtén tu IP pública: curl https://api.ipify.org"
        ;;
    2)
        echo ""
        echo "✅ Configurando conexión a través de proxy..."
        
        read -p "📝 URL del proxy (default: http://127.0.0.1:9000): " proxy_url
        proxy_url=${proxy_url:-http://127.0.0.1:9000}
        
        read -p "📝 Token del proxy: " proxy_token
        
        grep -q "USE_CRYPTO_PROXY" ../.env.local && \
            sed -i '' "s/USE_CRYPTO_PROXY=.*/USE_CRYPTO_PROXY=true/" ../.env.local || \
            echo "USE_CRYPTO_PROXY=true" >> ../.env.local
        
        grep -q "CRYPTO_PROXY_URL" ../.env.local && \
            sed -i '' "s|CRYPTO_PROXY_URL=.*|CRYPTO_PROXY_URL=${proxy_url}|" ../.env.local || \
            echo "CRYPTO_PROXY_URL=${proxy_url}" >> ../.env.local
        
        grep -q "CRYPTO_PROXY_TOKEN" ../.env.local && \
            sed -i '' "s/CRYPTO_PROXY_TOKEN=.*/CRYPTO_PROXY_TOKEN=${proxy_token}/" ../.env.local || \
            echo "CRYPTO_PROXY_TOKEN=${proxy_token}" >> ../.env.local
        
        grep -q "LIVE_TRADING" ../.env.local && \
            sed -i '' "s/LIVE_TRADING=.*/LIVE_TRADING=true/" ../.env.local || \
            echo "LIVE_TRADING=true" >> ../.env.local
        
        echo ""
        echo "✅ Configuración guardada en .env.local"
        echo ""
        echo "⚠️  IMPORTANTE: Asegúrate de que el proxy esté corriendo en ${proxy_url}"
        ;;
    3)
        echo ""
        echo "✅ Configurando modo Dry-Run..."
        
        grep -q "USE_CRYPTO_PROXY" ../.env.local && \
            sed -i '' "s/USE_CRYPTO_PROXY=.*/USE_CRYPTO_PROXY=false/" ../.env.local || \
            echo "USE_CRYPTO_PROXY=false" >> ../.env.local
        
        grep -q "LIVE_TRADING" ../.env.local && \
            sed -i '' "s/LIVE_TRADING=.*/LIVE_TRADING=false/" ../.env.local || \
            echo "LIVE_TRADING=false" >> ../.env.local
        
        echo ""
        echo "✅ Configuración guardada en .env.local"
        echo ""
        echo "ℹ️  Modo Dry-Run activado - Se usarán datos simulados"
        ;;
    *)
        echo "❌ Opción inválida"
        exit 1
        ;;
esac

echo ""
echo "============================================================"
echo "✅ Configuración completada"
echo "============================================================"
echo ""
echo "📋 Próximos pasos:"
echo "1. Reinicia el backend: docker compose restart backend"
echo "2. Prueba la conexión: docker compose exec backend python scripts/test_crypto_connection.py"
echo "3. Verifica los logs: docker compose logs -f backend"
echo ""


# Script para configurar la conexión a Crypto.com Exchange
# Este script te ayudará a configurar las variables de entorno necesarias

echo "============================================================"
echo "🔌 Configuración de Conexión a Crypto.com Exchange"
echo "============================================================"
echo ""

# Verificar si existe .env.local
if [ ! -f "../.env.local" ]; then
    echo "📝 Creando archivo .env.local..."
    touch ../.env.local
fi

echo "📋 Por favor, proporciona la siguiente información:"
echo ""

# Preguntar por el método de conexión
echo "¿Qué método de conexión quieres usar?"
echo "1) Conexión directa (requiere IP whitelisted)"
echo "2) Proxy (requiere proxy corriendo en puerto 9000)"
echo "3) Modo Dry-Run (datos simulados para testing)"
read -p "Opción (1-3): " connection_method

case $connection_method in
    1)
        echo ""
        echo "✅ Configurando conexión directa..."
        
        read -p "📝 API Key de Crypto.com Exchange: " api_key
        read -p "📝 API Secret de Crypto.com Exchange: " api_secret
        
        # Actualizar o agregar variables al .env.local
        grep -q "USE_CRYPTO_PROXY" ../.env.local && \
            sed -i '' "s/USE_CRYPTO_PROXY=.*/USE_CRYPTO_PROXY=false/" ../.env.local || \
            echo "USE_CRYPTO_PROXY=false" >> ../.env.local
        
        grep -q "LIVE_TRADING" ../.env.local && \
            sed -i '' "s/LIVE_TRADING=.*/LIVE_TRADING=true/" ../.env.local || \
            echo "LIVE_TRADING=true" >> ../.env.local
        
        grep -q "EXCHANGE_CUSTOM_API_KEY" ../.env.local && \
            sed -i '' "s/EXCHANGE_CUSTOM_API_KEY=.*/EXCHANGE_CUSTOM_API_KEY=${api_key}/" ../.env.local || \
            echo "EXCHANGE_CUSTOM_API_KEY=${api_key}" >> ../.env.local
        
        grep -q "EXCHANGE_CUSTOM_API_SECRET" ../.env.local && \
            sed -i '' "s/EXCHANGE_CUSTOM_API_SECRET=.*/EXCHANGE_CUSTOM_API_SECRET=${api_secret}/" ../.env.local || \
            echo "EXCHANGE_CUSTOM_API_SECRET=${api_secret}" >> ../.env.local
        
        echo ""
        echo "✅ Configuración guardada en .env.local"
        echo ""
        echo "⚠️  IMPORTANTE: Asegúrate de que tu IP está whitelisted en Crypto.com Exchange"
        echo "   Obtén tu IP pública: curl https://api.ipify.org"
        ;;
    2)
        echo ""
        echo "✅ Configurando conexión a través de proxy..."
        
        read -p "📝 URL del proxy (default: http://127.0.0.1:9000): " proxy_url
        proxy_url=${proxy_url:-http://127.0.0.1:9000}
        
        read -p "📝 Token del proxy: " proxy_token
        
        grep -q "USE_CRYPTO_PROXY" ../.env.local && \
            sed -i '' "s/USE_CRYPTO_PROXY=.*/USE_CRYPTO_PROXY=true/" ../.env.local || \
            echo "USE_CRYPTO_PROXY=true" >> ../.env.local
        
        grep -q "CRYPTO_PROXY_URL" ../.env.local && \
            sed -i '' "s|CRYPTO_PROXY_URL=.*|CRYPTO_PROXY_URL=${proxy_url}|" ../.env.local || \
            echo "CRYPTO_PROXY_URL=${proxy_url}" >> ../.env.local
        
        grep -q "CRYPTO_PROXY_TOKEN" ../.env.local && \
            sed -i '' "s/CRYPTO_PROXY_TOKEN=.*/CRYPTO_PROXY_TOKEN=${proxy_token}/" ../.env.local || \
            echo "CRYPTO_PROXY_TOKEN=${proxy_token}" >> ../.env.local
        
        grep -q "LIVE_TRADING" ../.env.local && \
            sed -i '' "s/LIVE_TRADING=.*/LIVE_TRADING=true/" ../.env.local || \
            echo "LIVE_TRADING=true" >> ../.env.local
        
        echo ""
        echo "✅ Configuración guardada en .env.local"
        echo ""
        echo "⚠️  IMPORTANTE: Asegúrate de que el proxy esté corriendo en ${proxy_url}"
        ;;
    3)
        echo ""
        echo "✅ Configurando modo Dry-Run..."
        
        grep -q "USE_CRYPTO_PROXY" ../.env.local && \
            sed -i '' "s/USE_CRYPTO_PROXY=.*/USE_CRYPTO_PROXY=false/" ../.env.local || \
            echo "USE_CRYPTO_PROXY=false" >> ../.env.local
        
        grep -q "LIVE_TRADING" ../.env.local && \
            sed -i '' "s/LIVE_TRADING=.*/LIVE_TRADING=false/" ../.env.local || \
            echo "LIVE_TRADING=false" >> ../.env.local
        
        echo ""
        echo "✅ Configuración guardada en .env.local"
        echo ""
        echo "ℹ️  Modo Dry-Run activado - Se usarán datos simulados"
        ;;
    *)
        echo "❌ Opción inválida"
        exit 1
        ;;
esac

echo ""
echo "============================================================"
echo "✅ Configuración completada"
echo "============================================================"
echo ""
echo "📋 Próximos pasos:"
echo "1. Reinicia el backend: docker compose restart backend"
echo "2. Prueba la conexión: docker compose exec backend python scripts/test_crypto_connection.py"
echo "3. Verifica los logs: docker compose logs -f backend"
echo ""


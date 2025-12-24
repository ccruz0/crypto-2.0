#!/bin/bash
# Script para ayudar a configurar variables de entorno requeridas

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
ENV_AWS="$PROJECT_ROOT/.env.aws"

echo "🔧 Configuración de Variables de Entorno para AWS"
echo "=================================================="
echo ""

# Verificar si .env.aws existe
if [ ! -f "$ENV_AWS" ]; then
    echo "📝 Creando archivo .env.aws..."
    touch "$ENV_AWS"
    chmod 600 "$ENV_AWS"
    echo "✅ Archivo creado"
else
    echo "✅ Archivo .env.aws existe"
fi
echo ""

# Variables requeridas (usando funciones para compatibilidad con bash 3.x)
get_var_desc() {
    case "$1" in
        OPENVPN_USER) echo "Usuario de OpenVPN/NordVPN" ;;
        OPENVPN_PASSWORD) echo "Contraseña de OpenVPN/NordVPN" ;;
        TELEGRAM_BOT_TOKEN) echo "Token del bot de Telegram" ;;
        TELEGRAM_CHAT_ID) echo "ID del chat de Telegram (puede ser negativo)" ;;
        SECRET_KEY) echo "Clave secreta para JWT (se generará automáticamente si no existe)" ;;
        POSTGRES_PASSWORD) echo "Contraseña de PostgreSQL" ;;
        CRYPTO_API_KEY) echo "API Key de Crypto.com" ;;
        CRYPTO_API_SECRET) echo "API Secret de Crypto.com" ;;
        CRYPTO_PROXY_TOKEN) echo "Token del proxy de Crypto.com" ;;
        *) echo "Variable requerida" ;;
    esac
}

REQUIRED_VARS="OPENVPN_USER OPENVPN_PASSWORD TELEGRAM_BOT_TOKEN TELEGRAM_CHAT_ID SECRET_KEY POSTGRES_PASSWORD CRYPTO_API_KEY CRYPTO_API_SECRET CRYPTO_PROXY_TOKEN"

# Función para verificar si una variable existe
var_exists() {
    local var_name="$1"
    grep -q "^${var_name}=" "$ENV_AWS" 2>/dev/null
}

# Función para obtener valor de variable
get_var_value() {
    local var_name="$1"
    grep "^${var_name}=" "$ENV_AWS" 2>/dev/null | cut -d'=' -f2- | sed 's/^["'\'']//;s/["'\'']$//'
}

# Generar SECRET_KEY si no existe
if ! var_exists "SECRET_KEY" || [ -z "$(get_var_value SECRET_KEY)" ] || [ "$(get_var_value SECRET_KEY)" = "your-secret-key-here" ]; then
    echo "🔑 Generando SECRET_KEY seguro..."
    NEW_SECRET_KEY=$(python3 -c "import secrets; print(secrets.token_urlsafe(32))")
    if var_exists "SECRET_KEY"; then
        # Reemplazar línea existente
        sed -i.bak "s|^SECRET_KEY=.*|SECRET_KEY=$NEW_SECRET_KEY|" "$ENV_AWS"
        rm -f "$ENV_AWS.bak"
    else
        # Agregar nueva línea
        echo "SECRET_KEY=$NEW_SECRET_KEY" >> "$ENV_AWS"
    fi
    echo "✅ SECRET_KEY generado y configurado"
else
    echo "✅ SECRET_KEY ya está configurado"
fi
echo ""

# Verificar y configurar otras variables
MISSING_VARS=""
for var_name in $REQUIRED_VARS; do
    if [ "$var_name" = "SECRET_KEY" ]; then
        continue  # Ya lo manejamos arriba
    fi
    
    if ! var_exists "$var_name" || [ -z "$(get_var_value "$var_name")" ]; then
        MISSING_VARS="$MISSING_VARS $var_name"
        echo "⚠️  FALTA: $var_name - $(get_var_desc "$var_name")"
    else
        echo "✅ $var_name está configurado"
    fi
done

echo ""

# Si hay variables faltantes, ofrecer ayuda
if [ -n "$MISSING_VARS" ]; then
    echo "📋 Variables faltantes encontradas:"
    for var in $MISSING_VARS; do
        echo "   - $var: $(get_var_desc "$var")"
    done
    echo ""
    echo "💡 Para agregar estas variables, edita .env.aws:"
    echo "   nano $ENV_AWS"
    echo ""
    echo "   O agrega manualmente:"
    for var in "${MISSING_VARS[@]}"; do
        echo "   $var=<valor>"
    done
    echo ""
    echo "⚠️  IMPORTANTE:"
    echo "   - No compartas estos valores"
    echo "   - .env.aws está en .gitignore (no se subirá a git)"
    echo "   - Usa valores seguros y únicos"
else
    echo "✅ Todas las variables requeridas están configuradas"
fi

echo ""
echo "🔍 Ejecutando validación..."
echo ""
python3 "$SCRIPT_DIR/validate_env_vars.py"


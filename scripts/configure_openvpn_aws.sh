#!/bin/bash
# Script para configurar credenciales de OpenVPN (NordVPN) en AWS

set -e

echo "🔐 Configuración de Credenciales OpenVPN (NordVPN) para AWS"
echo "============================================================"
echo ""
echo "Este script configurará las credenciales de NordVPN en el servidor AWS."
echo ""
echo "📋 Para obtener tus credenciales de NordVPN:"
echo "1. Ve a https://my.nordaccount.com/dashboard/nordvpn/"
echo "2. Inicia sesión en tu cuenta de NordVPN"
echo "3. Ve a 'Service credentials' o 'Manual setup'"
echo "4. Copia tu 'Username' y 'Password' para OpenVPN"
echo ""
echo "⚠️  NOTA: Estas credenciales son diferentes a tu usuario/contraseña de NordVPN"
echo "   Son credenciales específicas para conexiones OpenVPN"
echo ""

# Verificar si las credenciales se pasan como argumentos o variables de entorno
if [ -n "$1" ] && [ -n "$2" ]; then
    # Credenciales pasadas como argumentos
    OPENVPN_USER="$1"
    OPENVPN_PASSWORD="$2"
    echo "✅ Usando credenciales proporcionadas como argumentos"
elif [ -n "$OPENVPN_USER" ] && [ -n "$OPENVPN_PASSWORD" ]; then
    # Credenciales en variables de entorno
    echo "✅ Usando credenciales de variables de entorno"
else
    # Solicitar credenciales interactivamente
    read -p "🔑 Ingresa tu OPENVPN_USER (username de NordVPN): " OPENVPN_USER
    read -sp "🔐 Ingresa tu OPENVPN_PASSWORD (password de NordVPN): " OPENVPN_PASSWORD
    echo ""
fi

if [ -z "$OPENVPN_USER" ] || [ -z "$OPENVPN_PASSWORD" ]; then
    echo "❌ Error: Las credenciales no pueden estar vacías"
    echo ""
    echo "Uso:"
    echo "  $0 [USER] [PASSWORD]"
    echo "  o"
    echo "  OPENVPN_USER=user OPENVPN_PASSWORD=pass $0"
    echo "  o"
    echo "  $0  (modo interactivo)"
    exit 1
fi

echo ""
echo "📤 Configurando credenciales en el servidor AWS..."

# Actualizar el archivo .env.aws en el servidor
ssh hilovivo-aws << EOF
cd ~/crypto-2.0

# Backup del archivo actual
cp .env.aws .env.aws.backup.\$(date +%Y%m%d_%H%M%S)

# Actualizar o agregar las variables
if grep -q "^OPENVPN_USER=" .env.aws; then
    # Si existe, actualizar
    sed -i "s|^OPENVPN_USER=.*|OPENVPN_USER=$OPENVPN_USER|" .env.aws
else
    # Si no existe, agregar
    echo "OPENVPN_USER=$OPENVPN_USER" >> .env.aws
fi

if grep -q "^OPENVPN_PASSWORD=" .env.aws; then
    # Si existe, actualizar
    sed -i "s|^OPENVPN_PASSWORD=.*|OPENVPN_PASSWORD=$OPENVPN_PASSWORD|" .env.aws
else
    # Si no existe, agregar
    echo "OPENVPN_PASSWORD=$OPENVPN_PASSWORD" >> .env.aws
fi

echo "✅ Credenciales configuradas en .env.aws"
echo ""
echo "🔄 Reiniciando servicio gluetun..."
docker compose --profile aws restart gluetun || docker compose --profile aws up -d gluetun

echo ""
echo "⏳ Esperando a que gluetun se inicie..."
sleep 10

echo ""
echo "📊 Estado de gluetun:"
docker compose --profile aws ps gluetun

echo ""
echo "✅ Configuración completada!"
EOF

echo ""
echo "✅ Credenciales configuradas exitosamente"
echo ""
echo "📝 Próximos pasos:"
echo "1. Verifica que gluetun esté funcionando: ssh hilovivo-aws 'docker compose --profile aws ps gluetun'"
echo "2. Revisa los logs si hay problemas: ssh hilovivo-aws 'docker compose --profile aws logs gluetun'"
echo ""


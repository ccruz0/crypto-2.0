#!/bin/bash

# Script para probar la conexión SSH a la instancia EC2
# Uso: ./test_ssh_connection.sh [ruta-a-tu-clave.pem]

EC2_HOST="175.41.189.249"
EC2_USER="ubuntu"
# Unified SSH
. ./scripts/ssh_key.sh 2>/dev/null || source ./scripts/ssh_key.sh

echo "🔍 Probando conexión SSH a la instancia EC2..."
echo "📍 Host: $EC2_HOST"
echo "👤 Usuario: $EC2_USER"
echo "🔑 Clave: ${SSH_KEY:-$HOME/.ssh/id_rsa}"
echo ""

echo "🌐 Probando conectividad básica..."
ping -c 3 $EC2_HOST

echo ""
echo "🔐 Probando conexión SSH..."
ssh_cmd "$EC2_USER@$EC2_HOST" "echo '✅ SSH connection successful!' && uname -a"

if [ $? -eq 0 ]; then
    echo ""
    echo "🎉 ¡Conexión SSH exitosa!"
    echo "💡 Ahora puedes actualizar los secrets en GitHub:"
    echo "   - EC2_HOST: $EC2_HOST"
    echo "   - EC2_KEY: (contenido del archivo $KEY_FILE)"
else
    echo ""
    echo "❌ Falló la conexión SSH"
    echo "🔧 Verifica:"
    echo "   1. Security Group permite SSH (puerto 22) desde 0.0.0.0/0"
    echo "   2. La instancia está en estado 'running'"
    echo "   3. La clave .pem es correcta"
    echo "   4. El usuario es 'ubuntu' (para Ubuntu) o 'ec2-user' (para Amazon Linux)"
fi


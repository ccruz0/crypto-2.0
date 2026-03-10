#!/bin/bash
# Script para aplicar el fix de autorización de Telegram directamente en AWS
# Agrega TELEGRAM_AUTH_USER_ID=839853931 a .env.aws

set -e

echo "🔧 Aplicando fix de autorización de Telegram..."
echo ""

# Verificar si estamos en AWS o local
if [ -f ".env.aws" ]; then
    ENV_FILE=".env.aws"
    echo "📝 Actualizando $ENV_FILE localmente..."
    
    # Crear backup
    cp "$ENV_FILE" "${ENV_FILE}.backup.$(date +%Y%m%d_%H%M%S)"
    echo "✅ Backup creado"
    
    # Remover TELEGRAM_AUTH_USER_ID si existe
    if grep -q "^TELEGRAM_AUTH_USER_ID=" "$ENV_FILE"; then
        sed -i.bak "/^TELEGRAM_AUTH_USER_ID=/d" "$ENV_FILE"
        echo "✅ Removido TELEGRAM_AUTH_USER_ID existente"
    fi
    
    # Agregar TELEGRAM_AUTH_USER_ID después de TELEGRAM_CHAT_ID
    if grep -q "^TELEGRAM_CHAT_ID=" "$ENV_FILE"; then
        # macOS usa sed diferente
        if [[ "$OSTYPE" == "darwin"* ]]; then
            sed -i.bak "/^TELEGRAM_CHAT_ID=/a\\
TELEGRAM_AUTH_USER_ID=839853931" "$ENV_FILE"
        else
            sed -i "/^TELEGRAM_CHAT_ID=/a TELEGRAM_AUTH_USER_ID=839853931" "$ENV_FILE"
        fi
        echo "✅ Agregado TELEGRAM_AUTH_USER_ID=839853931"
    else
        # Si no existe TELEGRAM_CHAT_ID, agregar al final
        echo "" >> "$ENV_FILE"
        echo "TELEGRAM_AUTH_USER_ID=839853931" >> "$ENV_FILE"
        echo "✅ Agregado TELEGRAM_AUTH_USER_ID=839853931 al final del archivo"
    fi
    
    # Limpiar backup de sed
    rm -f "${ENV_FILE}.bak" 2>/dev/null || true
    
    echo ""
    echo "✅ Fix aplicado localmente en $ENV_FILE"
    echo ""
    echo "Configuración actualizada:"
    grep -E "TELEGRAM_(CHAT_ID|AUTH_USER_ID)" "$ENV_FILE" || echo "  (no encontrado)"
    echo ""
    echo "📤 Para aplicar en AWS, ejecuta:"
    echo "   scp .env.aws user@aws-server:/home/ubuntu/automated-trading-platform/.env.aws"
    echo "   ssh user@aws-server 'cd /home/ubuntu/automated-trading-platform && docker compose --profile aws restart backend-aws'"
    
elif command -v aws &> /dev/null; then
    echo "📤 Aplicando fix en AWS via SSM..."
    
    INSTANCE_ID="i-087953603011543c5"
    REGION="ap-southeast-1"
    
    aws ssm send-command \
      --instance-ids "$INSTANCE_ID" \
      --document-name "AWS-RunShellScript" \
      --parameters "commands=[
        \"cd /home/ubuntu/automated-trading-platform\",
        \"cp .env.aws .env.aws.backup.\\$(date +%Y%m%d_%H%M%S)\",
        \"if grep -q '^TELEGRAM_AUTH_USER_ID=' .env.aws; then sed -i '/^TELEGRAM_AUTH_USER_ID=/d' .env.aws; fi\",
        \"if grep -q '^TELEGRAM_CHAT_ID=' .env.aws; then sed -i '/^TELEGRAM_CHAT_ID=/a TELEGRAM_AUTH_USER_ID=839853931' .env.aws; else echo '' >> .env.aws; echo 'TELEGRAM_AUTH_USER_ID=839853931' >> .env.aws; fi\",
        \"echo 'Configuración actualizada:'\",
        \"grep -E 'TELEGRAM_(CHAT_ID|AUTH_USER_ID)' .env.aws\",
        \"docker compose --profile aws restart backend-aws\",
        \"sleep 5\",
        \"docker compose --profile aws logs backend-aws --tail=20 | grep -E '(AUTH.*Added|AUTH.*Authorized)' || echo 'Espera unos segundos y verifica los logs'\" 
      ]" \
      --region "$REGION" \
      --output json \
      --query 'Command.CommandId' \
      --output text
    
    echo ""
    echo "✅ Comando enviado a AWS"
    echo "⏳ Espera ~30 segundos y verifica:"
    echo "   aws ssm get-command-invocation --command-id <ID> --instance-id $INSTANCE_ID --region $REGION"
    
else
    echo "❌ No se encontró .env.aws localmente ni AWS CLI disponible"
    echo ""
    echo "Para aplicar manualmente en AWS:"
    echo "1. ssh hilovivo-aws"
    echo "2. cd /home/ubuntu/automated-trading-platform"
    echo "3. nano .env.aws"
    echo "4. Agregar: TELEGRAM_AUTH_USER_ID=839853931"
    echo "5. docker compose --profile aws restart backend-aws"
    exit 1
fi

echo ""
echo "✅ Fix completado!"









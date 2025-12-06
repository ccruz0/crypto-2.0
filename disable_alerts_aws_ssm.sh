#!/bin/bash
# Script para desactivar todas las alertas en AWS usando SSM

set -e

INSTANCE_ID="i-08726dc37133b2454"  # ID de la instancia EC2 de AWS

echo "🚫 Desactivando todas las alertas en AWS..."
echo "📋 Ejecutando script en instancia: $INSTANCE_ID"

# Ejecutar el script Python dentro del contenedor Docker en AWS
aws ssm send-command \
    --instance-ids "$INSTANCE_ID" \
    --document-name "AWS-RunShellScript" \
    --parameters "commands=[
        'cd /home/ubuntu/automated-trading-platform',
        'docker compose exec -T backend-aws python3 -c \"import sys; sys.path.insert(0, \\\"/app\\\"); exec(open(\\\"/tmp/disable_alerts.py\\\").read())\"'
    ]" \
    --output text \
    --query "Command.CommandId" \
    > /tmp/ssm_command_id.txt

COMMAND_ID=$(cat /tmp/ssm_command_id.txt)
echo "📝 Command ID: $COMMAND_ID"
echo "⏳ Esperando resultado..."

# Esperar a que el comando termine
sleep 5

# Obtener el resultado
aws ssm get-command-invocation \
    --command-id "$COMMAND_ID" \
    --instance-id "$INSTANCE_ID" \
    --query "[Status, StandardOutputContent, StandardErrorContent]" \
    --output text


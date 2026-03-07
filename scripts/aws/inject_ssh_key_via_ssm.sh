#!/usr/bin/env bash
# Inyecta la clave pública de ~/.ssh/atp-rebuild-2026.pem en la instancia EC2 vía SSM.
# Uso: ./scripts/aws/inject_ssh_key_via_ssm.sh [INSTANCE_ID]
# Requiere: SSM con PingStatus Online para la instancia.

set -e
INSTANCE_ID="${1:-i-087953603011543c5}"
PEM="${HOME}/.ssh/atp-rebuild-2026.pem"

if [[ ! -f "$PEM" ]]; then
  echo "No existe $PEM"
  exit 1
fi

echo "Comprobando SSM para $INSTANCE_ID..."
STATUS=$(aws ssm describe-instance-information --filters "Key=InstanceIds,Values=$INSTANCE_ID" --query 'InstanceInformationList[0].PingStatus' --output text 2>/dev/null || true)
if [[ "$STATUS" != "Online" ]]; then
  echo "SSM no está Online (status: $STATUS). Espera a que la instancia aparezca como Online y vuelve a ejecutar."
  exit 1
fi

echo "Obteniendo clave pública..."
PUBKEY=$(ssh-keygen -y -f "$PEM")
echo "Inyectando clave en $INSTANCE_ID..."
CMD_ID=$(aws ssm send-command \
  --instance-ids "$INSTANCE_ID" \
  --document-name "AWS-RunShellScript" \
  --parameters "commands=[\"mkdir -p /home/ubuntu/.ssh\", \"chmod 700 /home/ubuntu/.ssh\", \"echo '$PUBKEY' >> /home/ubuntu/.ssh/authorized_keys\", \"chmod 600 /home/ubuntu/.ssh/authorized_keys\"]" \
  --query 'Command.CommandId' --output text)

echo "CommandId: $CMD_ID"
echo "Esperando resultado..."
sleep 5
aws ssm get-command-invocation --command-id "$CMD_ID" --instance-id "$INSTANCE_ID" --query '{Status:Status,StdOut:StandardOutputContent,StdErr:StandardErrorContent}' --output table
echo ""
echo "Si Status es Success, prueba: ssh -i $PEM ubuntu@<PUBLIC_IP>"

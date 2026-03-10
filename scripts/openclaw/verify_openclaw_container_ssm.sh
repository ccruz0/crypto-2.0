#!/usr/bin/env bash
# ~30 s: ver qué imagen/contenedor OpenClaw está corriendo en LAB (vía SSM).
# Uso: ./scripts/openclaw/verify_openclaw_container_ssm.sh
# Requiere: AWS CLI, SSM Online en LAB.

set -e
AWS_REGION="${AWS_REGION:-ap-southeast-1}"
LAB_INSTANCE_ID="${LAB_INSTANCE_ID:-i-0d82c172235770a0d}"

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$REPO_ROOT"

echo "=== OpenClaw container check (LAB $LAB_INSTANCE_ID) ==="
STATUS=$(aws ssm describe-instance-information --region "$AWS_REGION" \
  --filters "Key=InstanceIds,Values=$LAB_INSTANCE_ID" \
  --query 'InstanceInformationList[0].PingStatus' --output text 2>/dev/null || echo "NotFound")
if [[ "$STATUS" != "Online" ]]; then
  echo "SSM PingStatus: $STATUS — run on server instead: docker ps | grep openclaw; docker images | grep openclaw"
  exit 1
fi

CMD_ID=$(aws ssm send-command \
  --instance-ids "$LAB_INSTANCE_ID" \
  --region "$AWS_REGION" \
  --document-name "AWS-RunShellScript" \
  --parameters 'commands=[
    "echo \"--- Containers (openclaw) ---\"",
    "docker ps --format \"{{.Image}}\t{{.Names}}\t{{.Status}}\" 2>/dev/null | grep -i openclaw || echo \"(none)\"",
    "echo \"\"",
    "echo \"--- Images (openclaw) ---\"",
    "docker images --format \"{{.Repository}}:{{.Tag}}\t{{.ID}}\" 2>/dev/null | grep -i openclaw || echo \"(none)\""
  ]' \
  --query 'Command.CommandId' --output text)

for i in $(seq 1 12); do
  S=$(aws ssm get-command-invocation --command-id "$CMD_ID" --instance-id "$LAB_INSTANCE_ID" --region "$AWS_REGION" --query 'Status' --output text 2>/dev/null || echo "Pending")
  [[ "$S" == "Success" || "$S" == "Failed" || "$S" == "Cancelled" ]] && break
  sleep 2
done

echo ""
aws ssm get-command-invocation --command-id "$CMD_ID" --instance-id "$LAB_INSTANCE_ID" --region "$AWS_REGION" --query 'StandardOutputContent' --output text 2>/dev/null || echo "(no output)"

echo ""
echo "--- Interpretación ---"
echo "ghcr.io/ccruz0/openclaw:latest = imagen real. crypto-2.0:openclaw o 'placeholder' = placeholder."

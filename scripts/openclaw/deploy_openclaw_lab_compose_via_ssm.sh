#!/usr/bin/env bash
# Deploy OpenClaw on LAB via docker-compose (builds ATP wrapper with docker.io on LAB).
# Uses docker-compose.openclaw.yml: Docker socket, group_add, ATP wrapper with docker CLI.
# Usage: ./scripts/openclaw/deploy_openclaw_lab_compose_via_ssm.sh
# Requires: AWS CLI, SSM access to LAB, repo at /home/ubuntu/crypto-2.0 on LAB.
set -euo pipefail

LAB_INSTANCE_ID="${LAB_INSTANCE_ID:-i-0d82c172235770a0d}"
AWS_REGION="${AWS_REGION:-ap-southeast-1}"
REPO_PATH="${ATP_REPO_PATH:-/home/ubuntu/crypto-2.0}"
DOCKER_GROUP_GID="${DOCKER_GROUP_GID:-988}"

echo "=== Deploying OpenClaw on LAB via docker-compose ($LAB_INSTANCE_ID) ==="

# Run as ubuntu (repo owner) to avoid git safe.directory; create host paths first as root
params=$(cat <<EOF
{
  "commands": [
    "set -e",
    "sudo mkdir -p /opt/openclaw/home-data",
    "sudo chown -R ubuntu:ubuntu /opt/openclaw 2>/dev/null || true",
    "sudo chown -R ubuntu:ubuntu $REPO_PATH 2>/dev/null || true",
    "sudo -u ubuntu bash -c 'cd $REPO_PATH && git fetch origin main && git checkout main && git pull origin main'",
    "sudo -u ubuntu bash -c 'cd $REPO_PATH && grep -q DOCKER_GROUP_GID .env.lab && sed -i.bak s/DOCKER_GROUP_GID=.*/DOCKER_GROUP_GID=$DOCKER_GROUP_GID/ .env.lab || echo DOCKER_GROUP_GID=$DOCKER_GROUP_GID >> .env.lab'",
    "echo === Stopping existing container ===",
    "sudo -u ubuntu sg docker -c 'cd $REPO_PATH && docker compose -f docker-compose.openclaw.yml down 2>/dev/null || true'",
    "docker stop openclaw 2>/dev/null || true",
    "docker rm openclaw 2>/dev/null || true",
    "echo === Building ATP wrapper and starting OpenClaw ===",
    "sudo -u ubuntu sg docker -c 'cd $REPO_PATH && OPENCLAW_IMAGE=openclaw-with-origins:latest docker compose -f docker-compose.openclaw.yml build --no-cache && OPENCLAW_IMAGE=openclaw-with-origins:latest docker compose -f docker-compose.openclaw.yml up -d'",
    "sleep 5",
    "echo === Verify Docker access inside container ===",
    "docker exec openclaw sh -c 'whoami && which docker && docker ps 2>&1 | head -3 && test -S /var/run/docker.sock && echo socket-present' 2>&1 || echo container-may-still-be-starting",
    "echo === Status ===",
    "sudo -u ubuntu sg docker -c 'cd $REPO_PATH && docker compose -f docker-compose.openclaw.yml ps'"
  ]
}
EOF
)

cmd_id=$(aws ssm send-command \
  --instance-ids "$LAB_INSTANCE_ID" \
  --region "$AWS_REGION" \
  --document-name "AWS-RunShellScript" \
  --parameters "$params" \
  --timeout-seconds 300 \
  --query 'Command.CommandId' \
  --output text)

echo "CommandId: $cmd_id"
echo "Waiting for completion (up to 180s)..."
for i in $(seq 1 36); do
  status=$(aws ssm get-command-invocation \
    --command-id "$cmd_id" \
    --instance-id "$LAB_INSTANCE_ID" \
    --region "$AWS_REGION" \
    --query 'Status' \
    --output text 2>/dev/null || echo "Pending")
  [[ "$status" == "Success" || "$status" == "Failed" || "$status" == "Cancelled" ]] && break
  sleep 5
  echo -n "."
done
echo ""

aws ssm get-command-invocation \
  --command-id "$cmd_id" \
  --instance-id "$LAB_INSTANCE_ID" \
  --region "$AWS_REGION" \
  --query '[Status, StandardOutputContent, StandardErrorContent]' \
  --output text

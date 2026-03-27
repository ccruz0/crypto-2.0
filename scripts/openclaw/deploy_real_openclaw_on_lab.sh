#!/usr/bin/env bash
# Run ON LAB (atp-lab-ssm-clean) to switch from placeholder to real OpenClaw image.
# Connect to LAB via: aws ssm start-session --target i-0d82c172235770a0d --region ap-southeast-1
#
# Usage on LAB:
#   cd /home/ubuntu/crypto-2.0
#   sudo bash scripts/openclaw/deploy_real_openclaw_on_lab.sh
#
# Optional: OPENCLAW_IMAGE=ghcr.io/ccruz0/openclaw:latest (default)

set -euo pipefail
REPO_ROOT="${REPO_ROOT:-/home/ubuntu/crypto-2.0}"
OPENCLAW_IMAGE="${OPENCLAW_IMAGE:-ghcr.io/ccruz0/openclaw:latest}"

cd "$REPO_ROOT"

echo "=== Deploy real OpenClaw image on LAB ==="
echo "Target image: $OPENCLAW_IMAGE"
echo ""

echo "Current container:"
docker ps --filter name=openclaw --format "table {{.Image}}\t{{.Status}}" 2>/dev/null || true

if [[ -f .env.lab ]]; then
  if grep -q '^OPENCLAW_IMAGE=' .env.lab; then
    sed -i.bak "s|^OPENCLAW_IMAGE=.*|OPENCLAW_IMAGE=$OPENCLAW_IMAGE|" .env.lab
  else
    echo "OPENCLAW_IMAGE=$OPENCLAW_IMAGE" >> .env.lab
  fi
  echo "Updated .env.lab OPENCLAW_IMAGE"
else
  echo "WARNING: .env.lab not found. Creating from example..."
  cp -n .env.lab.example .env.lab 2>/dev/null || true
  echo "OPENCLAW_IMAGE=$OPENCLAW_IMAGE" >> .env.lab
fi

echo ""
echo "Stopping, pulling, starting..."
docker compose -f docker-compose.openclaw.yml down
docker compose -f docker-compose.openclaw.yml pull
docker compose -f docker-compose.openclaw.yml up -d

echo ""
echo "Waiting 5s for container to start..."
sleep 5

echo ""
echo "Container status:"
docker compose -f docker-compose.openclaw.yml ps

echo ""
echo "Local check (expect real app, not placeholder):"
curl -sS -m 5 http://localhost:8080/ | head -20 || true

echo ""
echo "Verify in browser: https://dashboard.hilovivo.com/openclaw/ (Basic Auth)"

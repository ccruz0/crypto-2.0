#!/usr/bin/env bash
# Idempotent LAB OpenClaw bootstrap. Run as root on LAB via SSM.
# Ensures repo, .env.lab, secrets, /opt/openclaw/home-data, compose up, verify 8080.
set -euo pipefail

REPO="/home/ubuntu/automated-trading-platform"
COMPOSE="$REPO/docker-compose.openclaw.yml"
LOG(){ echo "[lab_bootstrap] $*"; }

LOG "=== 1) Docker ==="
command -v docker >/dev/null || { LOG "docker missing"; exit 1; }
docker info >/dev/null 2>&1 || { LOG "docker daemon not running"; exit 1; }

LOG "=== 2) /home/ubuntu and repo ==="
mkdir -p /home/ubuntu
id ubuntu &>/dev/null && chown ubuntu:ubuntu /home/ubuntu || true
chmod 755 /home/ubuntu

if [[ ! -d "$REPO/.git" ]]; then
  LOG "Cloning repo..."
  rm -rf "$REPO" 2>/dev/null || true
  sudo -u ubuntu git clone https://github.com/ccruz0/crypto-2.0.git "$REPO" 2>/dev/null || \
    git clone https://github.com/ccruz0/crypto-2.0.git "$REPO"
  id ubuntu &>/dev/null && chown -R ubuntu:ubuntu "$REPO"
fi

cd "$REPO"
git pull origin main 2>/dev/null || git pull 2>/dev/null || true

LOG "=== 3) .env.lab ==="
if [[ ! -f "$REPO/.env.lab" ]]; then
  if [[ -f "$REPO/.env.lab.example" ]]; then
    cp "$REPO/.env.lab.example" "$REPO/.env.lab"
    LOG "Created .env.lab from example"
  else
    LOG "FATAL: no .env.lab.example"; exit 1
  fi
fi

LOG "=== 4) secrets ==="
mkdir -p "$REPO/secrets"
touch "$REPO/secrets/runtime.env"
mkdir -p /home/ubuntu/secrets
touch /home/ubuntu/secrets/openclaw_token
chmod 600 /home/ubuntu/secrets/openclaw_token 2>/dev/null || true
id ubuntu &>/dev/null && chown -R ubuntu:ubuntu "$REPO/secrets" /home/ubuntu/secrets

LOG "=== 5) /opt/openclaw/home-data ==="
mkdir -p /opt/openclaw/home-data
chown -R 1000:1000 /opt/openclaw/home-data

LOG "=== 6) Compose up ==="
if [[ ! -f "$COMPOSE" ]]; then LOG "FATAL: missing $COMPOSE"; exit 1; fi
docker compose -f "$COMPOSE" down 2>/dev/null || true
docker compose -f "$COMPOSE" pull || { LOG "pull failed — may need: echo PAT | docker login ghcr.io -u ccruz0 --password-stdin"; exit 1; }
docker compose -f "$COMPOSE" up -d

LOG "=== 7) Verify ==="
sleep 3
docker ps -a --filter name=openclaw --format '{{.Names}} {{.Status}}'
ss -lntp 2>/dev/null | grep 8080 || true
HTTP=$(curl -sS -m 8 -o /dev/null -w "%{http_code}" http://127.0.0.1:8080/ || echo "000")
LOG "curl 127.0.0.1:8080/ -> HTTP $HTTP"
if [[ "$HTTP" =~ ^(200|301|302|401)$ ]]; then
  LOG "OK — OpenClaw responding on 8080"
  exit 0
fi
docker logs openclaw --tail 50 2>/dev/null || true
LOG "If HTTP not OK, check logs above"
exit 1

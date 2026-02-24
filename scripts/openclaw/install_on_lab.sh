#!/usr/bin/env bash
# OpenClaw LAB one-shot installer. Run ON the LAB instance (e.g. via SSM).
# Usage: bash install_on_lab.sh   (from repo root after clone)
#    or: bash <(curl -sSL https://raw.githubusercontent.com/ccruz0/crypto-2.0/main/scripts/openclaw/install_on_lab.sh)
# Requires: Ubuntu, sudo. Optional: set GIT_REPO_URL, OPENCLAW_IMAGE env before running.
set -e

REPO_DIR="${REPO_DIR:-/home/ubuntu/automated-trading-platform}"
GIT_REPO_URL="${GIT_REPO_URL:-https://github.com/ccruz0/crypto-2.0.git}"
OPENCLAW_IMAGE="${OPENCLAW_IMAGE:-ghcr.io/ccruz0/openclaw:latest}"

echo "=== 1) Apt over HTTPS ==="
sudo sed -i.bak 's|http://ap-southeast-1.ec2.archive.ubuntu.com|https://ap-southeast-1.ec2.archive.ubuntu.com|g' /etc/apt/sources.list 2>/dev/null || true
sudo sed -i 's|http://security.ubuntu.com|https://security.ubuntu.com|g' /etc/apt/sources.list 2>/dev/null || true
sudo sed -i 's|http://archive.ubuntu.com|https://archive.ubuntu.com|g' /etc/apt/sources.list 2>/dev/null || true
sudo apt update -qq || true
sudo apt install -y -qq apt-transport-https ca-certificates 2>/dev/null || true
sudo apt update -qq

echo "=== 2) Docker + Git ==="
sudo apt install -y docker.io docker-compose-v2 git
sudo usermod -aG docker "$(whoami)" 2>/dev/null || true

echo "=== 3) Repo ==="
if [ ! -d "$REPO_DIR/.git" ]; then
  sudo mkdir -p "$(dirname "$REPO_DIR")"
  sudo chown "$(whoami):$(whoami)" "$(dirname "$REPO_DIR")" 2>/dev/null || true
  git clone "$GIT_REPO_URL" "$REPO_DIR"
fi
cd "$REPO_DIR"
git fetch origin main 2>/dev/null || true
git checkout main 2>/dev/null || true

echo "=== 4) Token ==="
mkdir -p ~/secrets
chmod 700 ~/secrets
if [ ! -s ~/secrets/openclaw_token ]; then
  touch ~/secrets/openclaw_token
  chmod 600 ~/secrets/openclaw_token
  if [ -n "${OPENCLAW_TOKEN-}" ]; then
    echo -n "$OPENCLAW_TOKEN" > ~/secrets/openclaw_token
    unset OPENCLAW_TOKEN
  else
    echo "Paste your GitHub fine-grained PAT (Contents R/W, Pull requests R/W, Metadata R), then Enter:"
    read -r -s TOKEN
    echo -n "$TOKEN" > ~/secrets/openclaw_token
    unset TOKEN
  fi
fi
test -r ~/secrets/openclaw_token && echo "Token file OK" || { echo "ERROR: no token"; exit 1; }

echo "=== 5) .env.lab ==="
cp -n .env.lab.example .env.lab 2>/dev/null || true
chmod 600 .env.lab
OPENCLAW_TOKEN_PATH="${HOME}/secrets/openclaw_token"
grep -q '^GIT_REPO_URL=' .env.lab || echo "GIT_REPO_URL=$GIT_REPO_URL" >> .env.lab
grep -q '^OPENCLAW_TOKEN_PATH=' .env.lab || echo "OPENCLAW_TOKEN_PATH=$OPENCLAW_TOKEN_PATH" >> .env.lab
sed -i "s|^OPENCLAW_IMAGE=.*|OPENCLAW_IMAGE=$OPENCLAW_IMAGE|" .env.lab 2>/dev/null || true
grep -q '^OPENCLAW_IMAGE=' .env.lab || echo "OPENCLAW_IMAGE=$OPENCLAW_IMAGE" >> .env.lab
export OPENCLAW_TOKEN_PATH

echo "=== 6) Start OpenClaw ==="
# Use sg so docker group is active in this session
sg docker -c "cd $REPO_DIR && docker compose -f docker-compose.openclaw.yml up -d"
sg docker -c "cd $REPO_DIR && docker compose -f docker-compose.openclaw.yml ps"
echo "Logs: docker compose -f docker-compose.openclaw.yml logs -f openclaw"

echo "=== 7) Systemd (optional) ==="
if [ -f "$REPO_DIR/scripts/openclaw/openclaw.service" ]; then
  sudo cp "$REPO_DIR/scripts/openclaw/openclaw.service" /etc/systemd/system/
  sudo systemctl daemon-reload
  sudo systemctl enable openclaw 2>/dev/null || true
  echo "OpenClaw systemd service installed and enabled."
fi

echo ""
echo "=== Done. OpenClaw should be running. ==="
if sg docker -c "docker ps -q -f name=openclaw" 2>/dev/null | grep -q .; then
  echo "OK: openclaw container is running."
else
  echo "WARN: openclaw container not seen. Run: cd $REPO_DIR && docker compose -f docker-compose.openclaw.yml logs openclaw"
fi
echo "Logs: cd $REPO_DIR && docker compose -f docker-compose.openclaw.yml logs -f openclaw"

#!/usr/bin/env bash
# Run ON LAB: build OpenClaw wrapper (with pydantic-settings) and restart.
# Called by deploy_wrapper_build_on_lab_via_ssm.sh via SSM.
#
# Usage: cd /path/to/repo && sudo bash scripts/openclaw/do_wrapper_build_on_lab.sh

set -e

REPO="${REPO:-$(cd "$(dirname "$0")/../.." && pwd)}"
cd "$REPO"

OPENCLAW_HOME_DIR="${OPENCLAW_HOME_DIR:-/opt/openclaw/home-data}"
OPENCLAW_AGENT_WORKSPACE="${OPENCLAW_AGENT_WORKSPACE:-/workspace}"
OPENCLAW_CONFIG_IN_CONTAINER="/home/node/.openclaw/openclaw.json"
OPENCLAW_ALLOWED_ORIGINS="${OPENCLAW_ALLOWED_ORIGINS:-https://dashboard.hilovivo.com,http://localhost:18789,http://127.0.0.1:18789}"
OPENCLAW_TRUSTED_PROXIES="${OPENCLAW_TRUSTED_PROXIES:-172.31.32.169}"

echo "=== Git fetch + reset ==="
git fetch origin main
git reset --hard origin/main
grep -q pydantic-settings openclaw/Dockerfile.openclaw && echo "Dockerfile has pydantic step" || echo "WARN: Dockerfile missing pydantic step"

echo "=== Build wrapper ==="
sudo docker build --no-cache -f openclaw/Dockerfile.openclaw -t openclaw-with-origins:latest .

echo "=== Restart container ==="
sudo docker stop openclaw 2>/dev/null || true
sudo docker rm openclaw 2>/dev/null || true
sudo mkdir -p "$OPENCLAW_HOME_DIR/workspace"
sudo chown -R 1000:1000 "$OPENCLAW_HOME_DIR/workspace"
sudo chmod -R 775 "$OPENCLAW_HOME_DIR/workspace"
sudo docker run -d --restart unless-stopped -p 8080:18789 \
  -e OPENCLAW_ALLOWED_ORIGINS="$OPENCLAW_ALLOWED_ORIGINS" \
  -e OPENCLAW_TRUSTED_PROXIES="$OPENCLAW_TRUSTED_PROXIES" \
  -e OPENCLAW_CONFIG_PATH="$OPENCLAW_CONFIG_IN_CONTAINER" \
  -e OPENCLAW_AGENT_WORKSPACE="$OPENCLAW_AGENT_WORKSPACE" \
  -v "$OPENCLAW_HOME_DIR:/home/node/.openclaw" \
  -v "$REPO:/home/node/.openclaw/workspace/atp:ro" \
  -v "$OPENCLAW_HOME_DIR/agents:/home/node/openclaw/agents" \
  -v "$OPENCLAW_HOME_DIR/workspace:$OPENCLAW_AGENT_WORKSPACE" \
  --name openclaw openclaw-with-origins:latest

sleep 4
echo "=== Status ==="
sudo docker ps -a --filter name=openclaw
echo "=== Logs ==="
sudo docker logs openclaw --tail 30 2>&1

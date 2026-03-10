#!/usr/bin/env bash
# Run this ON the CLO/OpenCLO instance (Dashboard host) to:
#   1) Check if OpenClaw is running (systemd + docker)
#   2) Start it if not (systemctl or docker)
#   3) Verify nginx has the OpenClaw block and reload
#   4) Print diagnostics for paste (systemctl status + curl -I /openclaw/)
#
# Usage (on the instance):
#   cd /home/ubuntu/automated-trading-platform
#   sudo bash scripts/openclaw/check_and_start_openclaw.sh

set -e

REPO_ROOT="${REPO_ROOT:-/home/ubuntu/automated-trading-platform}"
cd "$REPO_ROOT"

echo "=== 1) Check if OpenClaw is already running ==="
sudo systemctl status openclaw --no-pager 2>/dev/null || true
echo ""
sudo docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}" 2>/dev/null | egrep -i "openclaw|claw" || true
echo ""

OPENCLAW_ACTIVE=0
if systemctl is-active --quiet openclaw 2>/dev/null; then
  OPENCLAW_ACTIVE=1
fi
if sudo docker ps --format "{{.Names}}" 2>/dev/null | grep -qi openclaw; then
  OPENCLAW_ACTIVE=1
fi

if [[ "$OPENCLAW_ACTIVE" -eq 0 ]]; then
  echo "=== 2) OpenClaw not running — starting ==="
  if [[ -f /etc/systemd/system/openclaw.service ]]; then
    sudo systemctl start openclaw
    sudo systemctl enable openclaw
    echo "Started and enabled openclaw.service"
    sudo systemctl status openclaw --no-pager
  else
    echo "No openclaw.service found. If you use Docker directly, run:"
    echo "  cd $REPO_ROOT && sudo docker compose -f docker-compose.openclaw.yml up -d"
    echo "Or install the unit: sudo cp $REPO_ROOT/scripts/openclaw/openclaw.service /etc/systemd/system/"
    echo "  sudo systemctl daemon-reload && sudo systemctl enable openclaw && sudo systemctl start openclaw"
    if [[ -f "$REPO_ROOT/docker-compose.openclaw.yml" ]] && [[ -t 0 ]] && [[ -z "${NONINTERACTIVE:-}${RUN_VIA_SSM:-}" ]]; then
      read -p "Start with docker compose now? [y/N] " -n 1 -r
      echo
      if [[ $REPLY =~ ^[Yy]$ ]]; then
        sudo docker compose -f "$REPO_ROOT/docker-compose.openclaw.yml" up -d
      fi
    fi
  fi
  echo ""
else
  echo "=== 2) OpenClaw already running — skip start ==="
  echo ""
fi

echo "=== 3) Verify nginx has the OpenClaw block ==="
sudo nginx -t
sudo systemctl reload nginx
echo ""

echo "=== 4) Diagnostics for paste (systemctl status + curl -I) ==="
echo "--- PASTE FROM HERE ---"
echo ""
echo "# systemctl status openclaw --no-pager"
sudo systemctl status openclaw --no-pager 2>/dev/null || echo "(openclaw.service not present or failed)"
echo ""
echo "# curl -sS -I https://dashboard.hilovivo.com/openclaw/"
curl -sS -I https://dashboard.hilovivo.com/openclaw/ 2>/dev/null | head -n 20
echo ""
echo "--- TO HERE ---"
echo ""

echo "=== 5) If you get 404 or blank, routing check ==="
echo "# Last 80 lines of nginx error log:"
sudo tail -n 80 /var/log/nginx/error.log 2>/dev/null || true
echo ""
echo "Open in browser: https://dashboard.hilovivo.com/openclaw/"

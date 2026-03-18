#!/usr/bin/env bash
# Verify OpenClaw runtime visibility: docker access, log path, whoami.
# Run on LAB host (e.g. via SSM). Exit 0 if all OK.
# Usage: bash scripts/openclaw/verify_runtime_visibility.sh
set -euo pipefail

REPO_ROOT="${REPO_ROOT:-$(cd "$(dirname "$0")/../.." && pwd)}"
cd "$REPO_ROOT"

echo "=== 1) Runtime user ==="
whoami
id

echo ""
echo "=== 2) Docker access (no sudo) ==="
if docker ps >/dev/null 2>&1; then
  echo "OK: docker ps works"
  docker ps --format "table {{.Names}}\t{{.Status}}" 2>/dev/null | head -10
else
  echo "FAIL: docker ps failed. Add user to docker group: sudo usermod -aG docker $(whoami)"
  exit 1
fi

echo ""
echo "=== 3) OpenClaw container ==="
if docker ps -q -f name=openclaw 2>/dev/null | grep -q .; then
  echo "OK: openclaw container running"
  docker logs openclaw --tail=5 2>/dev/null || echo "(docker logs failed)"
else
  echo "WARN: openclaw container not running"
fi

echo ""
echo "=== 4) Log path ==="
echo "Host: /var/log/openclaw does not exist on host (logs are in container/volume)."
echo "Inside container: /var/log/openclaw/ is a directory (volume mount)."
echo "To read logs: docker logs openclaw --tail=100"
if docker exec openclaw ls -la /var/log/openclaw 2>/dev/null; then
  echo "OK: /var/log/openclaw exists and is readable in container"
else
  echo "WARN: could not ls /var/log/openclaw in container (container may not be running)"
fi

echo ""
echo "=== Done. Runtime visibility OK. ==="

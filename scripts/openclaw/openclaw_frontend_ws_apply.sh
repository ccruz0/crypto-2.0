#!/usr/bin/env bash
# Run this script FROM the OpenClaw frontend repo root (the one that builds ghcr.io/ccruz0/openclaw).
# Usage: cd /path/to/openclaw-frontend && bash /path/to/this/script/openclaw_frontend_ws_apply.sh
# Or:    bash /path/to/openclaw_frontend_ws_apply.sh /path/to/openclaw-frontend
#
# IMPORTANT: Run from the OpenClaw frontend repo only. Running from ATP will scan the
# whole repo (including node_modules) and results will be misleading.

set -euo pipefail
REPO_ROOT="${1:-.}"
cd "$REPO_ROOT"

echo "=== Step A: Framework and layout (repo root: $(pwd)) ==="
echo "Note: Intended for OpenClaw frontend repo root. If this is ATP, run from the OpenClaw repo instead."
echo ""
if [ -f package.json ]; then
  echo "package.json exists."
  grep -E '"next"|"vite"|"@vitejs' package.json 2>/dev/null || true
fi
[ -d src ] && echo "Source root: src/"
[ -d app ] && echo "App dir: app/"
echo ""

echo "=== Step B: WebSocket and env matches ==="
echo "--- localhost:8081 ---"
grep -Rn "localhost:8081" --include="*.js" --include="*.ts" --include="*.tsx" --include="*.jsx" --include="*.vue" . 2>/dev/null || true
echo "--- ws://localhost ---"
grep -Rn "ws://localhost" --include="*.js" --include="*.ts" --include="*.tsx" --include="*.jsx" --include="*.vue" . 2>/dev/null || true
echo "--- new WebSocket( ---"
grep -Rn "new WebSocket(" --include="*.js" --include="*.ts" --include="*.tsx" --include="*.jsx" --include="*.vue" . 2>/dev/null || true
echo "--- ws:// ---"
grep -Rn "ws://" --include="*.js" --include="*.ts" --include="*.tsx" --include="*.jsx" --include="*.vue" . 2>/dev/null || true
echo "--- wss:// ---"
grep -Rn "wss://" --include="*.js" --include="*.ts" --include="*.tsx" --include="*.jsx" --include="*.vue" . 2>/dev/null || true
echo "--- NEXT_PUBLIC_OPENCLAW_WS_URL / NEXT_PUBLIC_ (first 15) ---"
grep -Rn "NEXT_PUBLIC_OPENCLAW_WS_URL\|NEXT_PUBLIC_" --include="*.js" --include="*.ts" --include="*.tsx" --include="*.jsx" --include="*.vue" . 2>/dev/null | head -15 || true
echo "--- VITE_OPENCLAW_WS_URL / VITE_ (first 15) ---"
grep -Rn "VITE_OPENCLAW_WS_URL\|VITE_" --include="*.js" --include="*.ts" --include="*.tsx" --include="*.jsx" --include="*.vue" . 2>/dev/null | head -15 || true
echo ""

echo "=== Step G: Verification (run AFTER applying patch) ==="
echo "1) localhost:8081 | ws://localhost (must be zero matches):"
grep -Rn "localhost:8081\|ws://localhost" --include="*.js" --include="*.ts" --include="*.tsx" --include="*.jsx" --include="*.vue" . 2>/dev/null || { echo "(no matches - OK)"; }
echo "2) new WebSocket | getOpenClawWsUrl:"
grep -Rn "new WebSocket\|getOpenClawWsUrl" --include="*.js" --include="*.ts" --include="*.tsx" --include="*.jsx" --include="*.vue" . 2>/dev/null || true

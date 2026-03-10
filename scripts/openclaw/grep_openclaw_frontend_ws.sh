#!/usr/bin/env bash
# Run Step A greps + verification in the OpenClaw FRONTEND repo.
# Usage:
#   cd /path/to/openclaw-frontend && bash /path/to/automated-trading-platform/scripts/openclaw/grep_openclaw_frontend_ws.sh
#   OR: bash scripts/openclaw/grep_openclaw_frontend_ws.sh /path/to/openclaw-frontend
#
# IMPORTANT: Run from the OpenClaw frontend repo root only. If run from ATP, greps will
# include node_modules and other non-OpenClaw code; pass the OpenClaw repo path as $1.
set -e

DIR="${1:-.}"
cd "$DIR"
echo "Running greps in: $(pwd)"
echo "Note: Intended for OpenClaw frontend repo root. Many node_modules hits mean you are likely in ATP."
echo ""

echo "=== localhost:8081 ==="
grep -Rn "localhost:8081" --include="*.js" --include="*.ts" --include="*.tsx" --include="*.jsx" --include="*.vue" . 2>/dev/null || true

echo ""
echo "=== WebSocket( ==="
grep -Rn "WebSocket(" --include="*.js" --include="*.ts" --include="*.tsx" --include="*.jsx" --include="*.vue" . 2>/dev/null || true

echo ""
echo "=== ws:// ==="
grep -Rn "ws://" --include="*.js" --include="*.ts" --include="*.tsx" --include="*.jsx" --include="*.vue" . 2>/dev/null || true

echo ""
echo "=== wss:// ==="
grep -Rn "wss://" --include="*.js" --include="*.ts" --include="*.tsx" --include="*.jsx" --include="*.vue" . 2>/dev/null || true

echo ""
echo "=== WS_URL ==="
grep -Rn "WS_URL" --include="*.js" --include="*.ts" --include="*.tsx" --include="*.jsx" --include="*.vue" . 2>/dev/null || true

echo ""
echo "=== NEXT_PUBLIC first 20 ==="
grep -Rn "NEXT_PUBLIC" --include="*.js" --include="*.ts" --include="*.tsx" --include="*.jsx" --include="*.vue" . 2>/dev/null | head -20 || true

echo ""
echo "=== VITE_ first 20 ==="
grep -Rn "VITE_" --include="*.js" --include="*.ts" --include="*.tsx" --include="*.jsx" --include="*.vue" . 2>/dev/null | head -20 || true

echo ""
echo "=== Verification: localhost WS (expect no matches after fix) ==="
grep -Rn "localhost:8081\|ws://localhost" --include="*.js" --include="*.ts" --include="*.tsx" --include="*.jsx" --include="*.vue" . 2>/dev/null || echo "no matches - OK"

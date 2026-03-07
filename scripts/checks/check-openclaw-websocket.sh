#!/usr/bin/env bash
set -euo pipefail

echo "Checking for forbidden WebSocket URLs in OpenClaw paths (code and config only)..."

SCAN_PATHS=()
for p in docs/openclaw scripts/openclaw openclaw; do
  [[ -d "$p" ]] && SCAN_PATHS+=("$p")
done

# Also scan any reference-frontend directories anywhere in the repo
while IFS= read -r d; do
  [[ -d "$d" ]] && SCAN_PATHS+=("$d")
done < <(find . -type d -name "reference-frontend" -prune 2>/dev/null || true)

if [[ ${#SCAN_PATHS[@]} -eq 0 ]]; then
  echo "✅ No OpenClaw paths to scan."
  exit 0
fi

MATCHES=$(grep -RInE 'ws://(localhost|127\.0\.0\.1)|new WebSocket\("ws://[^"]*"' \
  --include="*.ts" --include="*.tsx" --include="*.js" --include="*.jsx" --include="*.vue" \
  --include="*.env" \
  "${SCAN_PATHS[@]}" \
  2>/dev/null || true)

if [[ -n "$MATCHES" ]]; then
  echo ""
  echo "❌ Forbidden WebSocket URLs detected:"
  echo ""
  echo "$MATCHES"
  echo ""
  echo "OpenClaw WebSocket must be same-origin:"
  echo "  const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';"
  echo "  \`\${proto}//\${location.host}/openclaw/ws\`"
  echo ""
  echo "Or use helper: getOpenClawWsUrl()"
  exit 1
fi

echo "✅ No forbidden WebSocket URLs found."

#!/bin/bash
set -e

echo "🔍 Health Fix Verification Script"
echo "=================================="
echo ""

# Step 0: Wait for Docker
echo "Step 0: Checking Docker..."
if ! docker info >/dev/null 2>&1; then
  echo "❌ Docker Desktop is not running."
  echo ""
  echo "📋 Please start Docker Desktop manually:"
  echo "   1. Press Cmd+Space (Spotlight)"
  echo "   2. Type 'Docker Desktop' and press Enter"
  echo "   3. Wait until menu bar shows 'Docker Desktop is running'"
  echo ""
  echo "⏳ Waiting for Docker to start (max 4 minutes)..."
  for i in {1..120}; do
    if docker info >/dev/null 2>&1; then
      echo "✅ Docker is running!"
      break
    fi
    if [ $i -eq 120 ]; then
      echo "❌ Docker did not start within 4 minutes"
      exit 1
    fi
    sleep 2
  done
else
  echo "✅ Docker is running"
fi

echo ""
echo "Step 1: Starting backend..."
cd "$(dirname "$0")"
docker compose --profile local up -d --build backend

echo ""
echo "Step 2: Waiting for backend to be ready..."
for i in {1..30}; do
  if curl -sS http://localhost:8002/api/health >/dev/null 2>&1; then
    echo "✅ Backend ready!"
    break
  fi
  if [ $i -eq 30 ]; then
    echo "❌ Backend did not become ready"
    echo "📋 Checking logs..."
    docker compose --profile local logs --tail=50 backend
    exit 1
  fi
  echo "   Waiting... ($i/30)"
  sleep 2
done

echo ""
echo "Step 3: Testing endpoints..."
echo ""
echo "=== A) /api/health ==="
curl -sS -v http://localhost:8002/api/health 2>&1 | head -20

echo ""
echo "=== B) /api/health/system (THE FIX) ==="
RESPONSE=$(curl -sS -v http://localhost:8002/api/health/system 2>&1)
HTTP_STATUS=$(echo "$RESPONSE" | grep -i "< HTTP" | head -1 | awk '{print $3}')
echo "$RESPONSE" | head -40

if echo "$RESPONSE" | grep -q '"detail":"Not Found"'; then
  echo ""
  echo "❌ FAIL: Endpoint still returns 404"
  echo "📋 Checking route registration..."
  docker compose --profile local exec backend python3 -c "
from app.main import app
routes = [r.path for r in app.routes if 'health' in r.path.lower()]
print('Registered health routes:')
for r in sorted(routes):
    print(f'  {r}')
" 2>&1 || echo "Could not inspect routes"
  exit 1
elif [ "$HTTP_STATUS" != "200" ]; then
  echo ""
  echo "❌ FAIL: HTTP status is $HTTP_STATUS (expected 200)"
  exit 1
else
  echo ""
  echo "✅ PASS: /api/health/system returns HTTP 200"
fi

echo ""
echo "Step 4: Running Playwright QA..."
cd frontend
npm run qa:local-dashboard

echo ""
echo "Step 5: Collecting evidence..."
echo ""
echo "=== QA Summary ==="
cat tmp/local_qa_run/summary.md

echo ""
echo "=== API Failures ==="
cat tmp/local_qa_run/network.json | python3 -c "
import sys, json
data = json.load(sys.stdin)
failures = data.get('apiFailures', [])
print(f'Total failures: {len(failures)}')
for f in failures:
    print(f\"  - {f.get('url', 'N/A')} (Status: {f.get('status', 'N/A')})\")
" 2>&1 || echo "No failures found"

echo ""
echo "=== Evidence Files ==="
echo "Screenshots:"
ls -lh tmp/local_qa_run/*.png 2>/dev/null | awk '{print "  " $9 " (" $5 ")"}' || echo "  No screenshots found"
echo ""
echo "Data files:"
ls -lh tmp/local_qa_run/*.json tmp/local_qa_run/*.md 2>/dev/null | awk '{print "  " $9}' || echo "  No data files found"

echo ""
echo "✅ Verification complete!"




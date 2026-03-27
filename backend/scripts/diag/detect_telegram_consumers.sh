#!/usr/bin/env bash
# Detect all Telegram consumers that could be polling getUpdates with TELEGRAM_BOT_TOKEN.
#
# Run on PROD (EC2 or via SSM) to identify duplicate pollers causing:
#   - "Unknown command. Use /help."
#   - "Already processed. Try again in a moment."
#
# Usage:
#   ./backend/scripts/diag/detect_telegram_consumers.sh
#   # Or via SSM:
#   aws ssm send-command --instance-ids i-xxx --document-name AWS-RunShellScript \
#     --parameters 'commands=["cd /home/ubuntu/crypto-2.0 && bash backend/scripts/diag/detect_telegram_consumers.sh"]'
#
# Output: process name, container name, command, which file handles Telegram updates.

set -euo pipefail

echo "=== TELEGRAM CONSUMER DETECTION ==="
echo ""

# 1. Docker containers
echo "--- 1. DOCKER CONTAINERS (profile aws) ---"
if command -v docker >/dev/null 2>&1; then
  docker ps -a --format 'table {{.Names}}\t{{.Status}}\t{{.Image}}' 2>/dev/null | head -30
  echo ""
  echo "Containers that may poll Telegram:"
  for c in $(docker ps -a --format '{{.Names}}' 2>/dev/null | grep -E 'backend-aws|market-updater' || true); do
    if docker ps -a --format '{{.Names}}' 2>/dev/null | grep -q "$c"; then
      echo "  - $c: $(docker inspect "$c" --format '{{.State.Status}}' 2>/dev/null || echo 'not found')"
      run_tg=$(docker exec "$c" printenv RUN_TELEGRAM_POLLER 2>/dev/null || echo "N/A")
      run_tg_val="${run_tg:-true}"
      echo "    RUN_TELEGRAM_POLLER=$run_tg_val"
    fi
  done 2>/dev/null || true
else
  echo "  docker not found"
fi
echo ""

# 2. Docker Compose services
echo "--- 2. DOCKER COMPOSE SERVICES ---"
if [[ -f docker-compose.yml ]]; then
  if command -v docker >/dev/null 2>&1; then
    docker compose --profile aws ps 2>/dev/null || docker-compose --profile aws ps 2>/dev/null || echo "  compose ps failed"
  fi
else
  echo "  docker-compose.yml not found (run from repo root)"
fi
echo ""

# 3. Python processes that might run scheduler/telegram
echo "--- 3. PYTHON PROCESSES (gunicorn, uvicorn, run_updater) ---"
ps aux 2>/dev/null | grep -E 'gunicorn|uvicorn|run_updater|python.*main' | grep -v grep || echo "  none found"
echo ""

# 4. Container env (TELEGRAM vars)
echo "--- 4. CONTAINER ENV (TELEGRAM vars) ---"
for c in $(docker ps --format '{{.Names}}' 2>/dev/null | grep -E 'backend-aws|market-updater' || true); do
  if docker ps --format '{{.Names}}' 2>/dev/null | grep -q "$c"; then
    echo "  $c:"
    docker exec "$c" printenv 2>/dev/null | grep -E '^RUN_TELEGRAM|^RUN_TELEGRAM_POLLER|^RUNTIME_ORIGIN|^APP_ENV' || echo "    (no match)"
  fi
done 2>/dev/null || true
echo ""

# 5. Advisory lock holder (if we can query DB)
echo "--- 5. POSTGRES ADVISORY LOCK (TELEGRAM_POLLER_LOCK_ID=1234567890) ---"
if command -v docker >/dev/null 2>&1; then
  db_container=$(docker ps --format '{{.Names}}' 2>/dev/null | grep -E 'postgres|db' | head -1)
  if [[ -n "$db_container" ]]; then
    docker exec "$db_container" psql -U trader -d atp -t -c "
      SELECT pid, state, query_start, left(query, 80)
      FROM pg_stat_activity
      WHERE query LIKE '%advisory%' OR query LIKE '%1234567890%'
      LIMIT 5;
    " 2>/dev/null || echo "  (cannot query DB)"
  else
    echo "  postgres container not found"
  fi
else
  echo "  docker not available"
fi
echo ""

# 6. getWebhookInfo - confirms polling vs webhook (run inside backend-aws)
echo "--- 6. TELEGRAM getWebhookInfo ---"
backend_c=$(docker ps --format '{{.Names}}' 2>/dev/null | grep 'backend-aws' | grep -v canary | head -1)
if [[ -n "$backend_c" ]]; then
  docker exec "$backend_c" python -c "
import os, json, urllib.request
t = (os.getenv('TELEGRAM_BOT_TOKEN') or os.getenv('TELEGRAM_BOT_TOKEN_AWS') or '').strip()
if t:
    r = urllib.request.urlopen(f'https://api.telegram.org/bot{t}/getWebhookInfo', timeout=5)
    d = json.loads(r.read())
    url = d.get('result', {}).get('url', '')
    print(f'  Webhook: {url or \"None (polling mode)\"}')
else:
    print('  No token in env')
" 2>/dev/null || echo "  (token/import failed)"
else
  echo "  backend-aws container not running"
fi
echo ""

echo "=== SUMMARY ==="
echo "Expected: ONLY backend-aws should poll. backend-aws-canary must have RUN_TELEGRAM_POLLER=false."
echo "If multiple containers have RUN_TELEGRAM_POLLER=true or unset, that causes duplicate pollers."
echo ""

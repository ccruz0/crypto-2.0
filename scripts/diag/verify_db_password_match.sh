#!/usr/bin/env bash
# Verify that backend-aws can connect to the DB (password in DATABASE_URL matches POSTGRES_PASSWORD).
# No secrets are printed. Exit 0 if DB connection OK, 1 otherwise.
# Usage: ./scripts/diag/verify_db_password_match.sh

set -e
REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$REPO_ROOT"

echo "Checking DB connection from backend-aws container..."
if docker exec automated-trading-platform-backend-aws-1 python -c "
import sys
sys.path.insert(0, '/app')
from sqlalchemy import text
from app.database import SessionLocal
db = SessionLocal()
db.execute(text('SELECT 1'))
db.close()
print('DB_OK')
" 2>/dev/null; then
  echo "DB connection: OK"
  echo "Checking /api/health/system..."
  db_status=$(curl -sS --max-time 10 http://127.0.0.1:8002/api/health/system 2>/dev/null | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('db_status','?'))" 2>/dev/null || echo "?")
  echo "db_status: $db_status"
  [ "$db_status" = "up" ] && exit 0 || exit 1
else
  echo "DB connection: FAIL (password auth or unreachable)"
  exit 1
fi

#!/usr/bin/env bash
# Idempotent bootstrap: ensure order_intents table exists.
# Safe to run repeatedly. No secrets printed.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"
SQL_FILE="$ROOT/scripts/aws/bootstrap_order_intents.sql"

if [[ ! -f "$SQL_FILE" ]]; then
    echo "FAIL"
    exit 1
fi

# Ensure db is up
docker compose --profile aws up -d db 2>/dev/null || true
sleep 5
for _ in 1 2 3 4 5 6; do
    if docker compose --profile aws exec -T db pg_isready -U trader -d atp 2>/dev/null; then
        break
    fi
    sleep 5
done

# Run SQL: source .env.aws in subshell for password (never printed), then exec db psql
run_sql() {
    ( set +u; [ -f "$ROOT/.env.aws" ] && . "$ROOT/.env.aws"; set -u
      export PGPASSWORD="${POSTGRES_PASSWORD:-}"
      cat "$SQL_FILE" | docker compose --profile aws exec -T -e PGPASSWORD db psql -U trader -d atp -f - -q 2>/dev/null
    )
}

if ! run_sql; then
    # Fallback: via backend-aws if up
    if docker compose --profile aws ps -a --format '{{.Service}} {{.Status}}' 2>/dev/null | grep -qE '^backend-aws .*Up '; then
        if docker compose --profile aws exec -T backend-aws python -c "
import os, sys
from sqlalchemy import create_engine, text
dsn = (os.environ.get('DATABASE_URL') or '').strip()
if not dsn: sys.exit(1)
e = create_engine(dsn)
p = '/app/scripts/aws/bootstrap_order_intents.sql'
with open(p) as f: content = f.read()
for stmt in content.split(';'):
    s = stmt.strip()
    if s and not s.startswith('--'):
        with e.connect() as c: c.execute(text(s + ';')); c.commit()
r = e.connect().execute(text(\"select to_regclass('public.order_intents')\")).scalar()
sys.exit(0 if r else 1)
" 2>/dev/null; then
            echo "PASS"
            exit 0
        fi
    fi
    echo "FAIL"
    exit 1
fi

# Verify table exists
check=$(docker compose --profile aws exec -T db psql -U trader -d atp -t -c "SELECT to_regclass('public.order_intents');" 2>/dev/null || true)
if echo "$check" | grep -q order_intents; then
    echo "PASS"
    exit 0
fi
echo "FAIL"
exit 1

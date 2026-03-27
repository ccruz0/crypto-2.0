#!/usr/bin/env bash
# Bootstrap DB schema: ensure watchlist_items (and order_intents, market_data, market_price) exist.
# Run from repo root. Uses backend container to call ensure_optional_columns (no Alembic).
# Exit 0 if schema OK or created; non-zero if we cannot ensure schema.
#
# Usage:
#   cd /home/ubuntu/crypto-2.0
#   ./scripts/db/bootstrap.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$REPO_ROOT"

POSTGRES_CONTAINER="${POSTGRES_CONTAINER:-postgres_hardened}"
BACKEND_CONTAINER="${BACKEND_CONTAINER:-automated-trading-platform-backend-aws-1}"

# Check if watchlist_items exists (via backend container so we don't need postgres password on host)
check_watchlist_table() {
  docker exec "$BACKEND_CONTAINER" python -c "
from app.database import engine
from sqlalchemy import inspect
if engine is None:
    raise SystemExit(1)
insp = inspect(engine)
print('1' if 'watchlist_items' in insp.get_table_names() else '')
" 2>/dev/null || echo ""
}

# Run schema ensure via backend (ensure_optional_columns creates watchlist_items, order_intents, market_data, market_price)
run_schema_ensure() {
  if docker ps --format '{{.Names}}' | grep -q "^${BACKEND_CONTAINER}$"; then
    docker exec "$BACKEND_CONTAINER" python -c "
from app.database import engine, ensure_optional_columns
if engine is None:
    raise SystemExit('Database engine not configured')
ensure_optional_columns(engine)
print('Schema ensure completed.')
" 2>/dev/null
  else
    docker compose --profile aws run --rm backend-aws python -c "
from app.database import engine, ensure_optional_columns
if engine is None:
    raise SystemExit('Database engine not configured')
ensure_optional_columns(engine)
print('Schema ensure completed.')
" 2>/dev/null
  fi
}

if [ -z "$(check_watchlist_table)" ]; then
  echo "watchlist_items missing — running schema bootstrap..."
  if ! run_schema_ensure; then
    echo "Bootstrap failed. Ensure Postgres is up and backend can connect (DATABASE_URL)."
    echo "  docker compose --profile aws ps"
    exit 1
  fi
  # Verify
  if [ -z "$(check_watchlist_table)" ]; then
    echo "Bootstrap ran but watchlist_items still missing."
    exit 1
  fi
  echo "watchlist_items created."
else
  echo "watchlist_items already exists."
fi
exit 0

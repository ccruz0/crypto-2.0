#!/bin/bash
# Stage and commit only the trigger-orders fallback + UI + redeploy (no secrets, no frontend submodule paths from root).
# Run from repo root: ./scripts/commit_trigger_orders_changes.sh
set -e
cd "$(dirname "$0")/.."

echo "Staging trigger-orders related files (backend + runbook + redeploy only)..."
git add \
  backend/app/api/routes_orders.py \
  backend/app/services/brokers/crypto_com_trade.py \
  backend/app/services/open_orders.py \
  backend/Dockerfile.aws \
  backend/scripts/diagnose_open_vs_trigger_orders.py \
  docs/runbooks/OPEN_VS_TRIGGER_ORDERS_DIAGNOSTIC.md \
  redeploy.sh

echo "Staged:"
git diff --cached --name-only

echo ""
read -p "Commit with message 'Trigger orders 40101 fallback, Open/Trigger Orders UI, redeploy script'? (y/N): " -r
if [[ ! "$REPLY" =~ ^[Yy]$ ]]; then
  echo "Aborted. Unstaging..."
  git restore --staged .
  exit 0
fi

git commit -m "Trigger orders 40101 fallback, Open/Trigger Orders UI, redeploy script"
echo "Done. Push with: git push origin main"

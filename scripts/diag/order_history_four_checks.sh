#!/usr/bin/env bash
# Executed-orders diagnostic: 3 checks (sync, DB count, API read). Run on EC2 where Docker + backend run.
# Usage: cd /home/ubuntu/automated-trading-platform && sudo ./scripts/diag/order_history_four_checks.sh
# See: docs/runbooks/ORDER_HISTORY_DASHBOARD_DEBUG.md
set -e
cd /home/ubuntu/automated-trading-platform
CONTAINER="${BACKEND_CONTAINER:-automated-trading-platform-backend-aws-1}"

echo "=== 1. Force sync (symbol=ATOM_USDT) ==="
curl -s "http://127.0.0.1:8002/api/orders/history?symbol=ATOM_USDT&limit=10&offset=0&sync=true" | head -c 400
echo
echo ""

echo "=== 2. DB count and sample rows (ExchangeOrder, ATOM_USDT) ==="
sudo docker exec -it "$CONTAINER" sh -lc '
python - << "PY"
from app.database import SessionLocal
from app.models.exchange_order import ExchangeOrder
db = SessionLocal()
q = db.query(ExchangeOrder).filter(ExchangeOrder.symbol=="ATOM_USDT")
print("COUNT:", q.count())
for o in q.order_by(ExchangeOrder.created_at.desc()).limit(5):
    print(o.id, o.symbol, o.status, o.side, o.created_at)
db.close()
PY
'
echo ""

echo "=== 3. API read path (sync=false) ==="
curl -s "http://127.0.0.1:8002/api/orders/history?symbol=ATOM_USDT&limit=5&offset=0&sync=false" | head -c 600
echo
echo ""

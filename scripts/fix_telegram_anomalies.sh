#!/usr/bin/env bash
# Fix the two common Telegram anomalies:
# 1. Amount USD not configured for BTC_USD (automatic order creation failed)
# 2. Scheduler inactivity (agent scheduler cycle not seen)
#
# Run from repo root. On AWS with Docker:
#   ./scripts/fix_telegram_anomalies.sh
#
# Options:
#   BTC_AMOUNT_USD=100  ./scripts/fix_telegram_anomalies.sh   # Custom amount for BTC_USD (default: 50)

set -e
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

BTC_AMOUNT_USD="${BTC_AMOUNT_USD:-50}"

echo "=== Fix Telegram Anomalies ==="
echo ""

# 1. Set Amount USD for BTC_USD
echo "1. Setting trade_amount_usd=\$${BTC_AMOUNT_USD} for BTC_USD..."
if command -v docker >/dev/null 2>&1 && docker compose --profile aws ps backend-aws 2>/dev/null | grep -q Up; then
  docker compose --profile aws exec backend-aws python scripts/set_watchlist_trade_amount.py BTC_USD "$BTC_AMOUNT_USD" || true
else
  cd "$REPO_ROOT/backend"
  if [ -f "$REPO_ROOT/secrets/runtime.env" ]; then set -a; source "$REPO_ROOT/secrets/runtime.env" 2>/dev/null; set +a; fi
  if [ -f ".env" ]; then set -a; source .env 2>/dev/null; set +a; fi
  if [ -x ".venv/bin/python" ]; then
    .venv/bin/python scripts/set_watchlist_trade_amount.py BTC_USD "$BTC_AMOUNT_USD" || true
  else
    python scripts/set_watchlist_trade_amount.py BTC_USD "$BTC_AMOUNT_USD" || true
  fi
fi
echo ""

# 2. Run one agent scheduler cycle (seeds activity log, clears scheduler_inactivity)
echo "2. Running one agent scheduler cycle (seeds activity log)..."
"$REPO_ROOT/scripts/run_notion_task_pickup.sh" 2>/dev/null || true
echo ""

echo "Done. Check Telegram for new alerts."

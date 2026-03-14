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

# 1. Set Amount USD for BTC_USD (only when backend-aws is running — needs PostgreSQL)
echo "1. Setting trade_amount_usd=\$${BTC_AMOUNT_USD} for BTC_USD..."
if command -v docker >/dev/null 2>&1 && docker compose --profile aws ps backend-aws 2>/dev/null | grep -q Up; then
  docker compose --profile aws exec backend-aws python scripts/set_watchlist_trade_amount.py BTC_USD "$BTC_AMOUNT_USD" || true
else
  echo "   (Skipped: backend-aws not running. Run on PROD via: ./scripts/fix_telegram_anomalies_via_ssm.sh)"
fi
echo ""

# 2. Run one agent scheduler cycle (seeds activity log, clears scheduler_inactivity)
echo "2. Running one agent scheduler cycle (seeds activity log)..."
if command -v docker >/dev/null 2>&1 && docker compose --profile aws ps backend-aws 2>/dev/null | grep -q Up; then
  docker compose --profile aws exec -T backend-aws python scripts/run_agent_scheduler_cycle.py 2>/dev/null || true
else
  echo "   (Skipped: backend-aws not running. Run on PROD via: ./scripts/fix_telegram_anomalies_via_ssm.sh)"
fi
echo ""

echo "Done. Check Telegram for new alerts."

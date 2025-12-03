#!/usr/bin/env bash
# Debug script for alert pipeline - fetches logs from remote AWS backend
# Usage: bash scripts/debug_alert_pipeline_remote.sh SYMBOL [WINDOW_MIN]

set -euo pipefail

# Validate arguments
if [ $# -lt 1 ]; then
    echo "Usage: $0 SYMBOL [WINDOW_MIN]"
    echo ""
    echo "SYMBOL: Trading symbol (e.g., TON_USDT, BTC_USDT)"
    echo "WINDOW_MIN: Time window in minutes (default: 30)"
    echo ""
    echo "Example:"
    echo "  $0 TON_USDT 30"
    exit 1
fi

SYMBOL="$1"
WINDOW_MIN="${2:-30}"

echo "==================================================================="
echo "ALERT PIPELINE DEBUG for $SYMBOL (last ${WINDOW_MIN}m)"
echo "==================================================================="
echo ""

# Section 1: Strategy (DEBUG_STRATEGY_FINAL)
echo "==================================================================="
echo "STRATEGY: DEBUG_STRATEGY_FINAL for $SYMBOL (last ${WINDOW_MIN}m)"
echo "==================================================================="
ssh hilovivo-aws 'cd /home/ubuntu/automated-trading-platform && docker compose logs backend-aws --since='"${WINDOW_MIN}"'m 2>&1 | grep "'"$SYMBOL"'" | grep DEBUG_STRATEGY_FINAL | tail -n 50' || echo "(No strategy logs found)"
echo ""

# Section 2: SignalMonitor
echo "==================================================================="
echo "SIGNAL MONITOR for $SYMBOL (last ${WINDOW_MIN}m)"
echo "==================================================================="
ssh hilovivo-aws 'cd /home/ubuntu/automated-trading-platform && docker compose logs backend-aws --since='"${WINDOW_MIN}"'m 2>&1 | grep "'"$SYMBOL"'" | grep -E "(SignalMonitor|DEBUG_SIGNAL_MONITOR)" | tail -n 80' || echo "(No signal monitor logs found)"
echo ""

# Section 3: Alert helper (ALERT_ logs)
echo "==================================================================="
echo "ALERT PIPELINE (ALERT_ logs) for $SYMBOL (last ${WINDOW_MIN}m)"
echo "==================================================================="
ssh hilovivo-aws 'cd /home/ubuntu/automated-trading-platform && docker compose logs backend-aws --since='"${WINDOW_MIN}"'m 2>&1 | grep "'"$SYMBOL"'" | grep ALERT_ | tail -n 80' || echo "(No alert pipeline logs found)"
echo ""

# Section 4: Telegram logs
echo "==================================================================="
echo "TELEGRAM logs for $SYMBOL (last ${WINDOW_MIN}m)"
echo "==================================================================="
ssh hilovivo-aws 'cd /home/ubuntu/automated-trading-platform && docker compose logs backend-aws --since='"${WINDOW_MIN}"'m 2>&1 | grep "'"$SYMBOL"'" | grep -E "(TELEGRAM_SEND|TELEGRAM_ERROR|TELEGRAM)" | tail -n 80' || echo "(No Telegram logs found)"
echo ""

echo "==================================================================="
echo "DEBUG COMPLETE"
echo "==================================================================="

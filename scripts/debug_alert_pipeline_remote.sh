#!/usr/bin/env bash
# Debug script for alert pipeline - fetches logs from remote AWS backend
# Usage: bash scripts/debug_alert_pipeline_remote.sh SYMBOL [WINDOW_MIN]
# All timestamps are displayed in Bali time (UTC+8)

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

# Function to convert UTC timestamps to Bali time (UTC+8)
# Uses awk to add 8 hours to UTC timestamps
convert_to_bali_time() {
    awk '{
        # Match timestamp pattern: YYYY-MM-DD HH:MM:SS
        if (match($0, /([0-9]{4}-[0-9]{2}-[0-9]{2}) ([0-9]{2}):([0-9]{2}):([0-9]{2})/)) {
            date = substr($0, RSTART, RLENGTH)
            split(date, parts, /[- :]/)
            year = parts[1]
            month = parts[2]
            day = parts[3]
            hour = int(parts[4])
            min = parts[5]
            sec = parts[6]
            
            # Add 8 hours for Bali time (UTC+8)
            hour = hour + 8
            if (hour >= 24) {
                hour = hour - 24
                day = day + 1
            }
            
            # Format with leading zeros
            hour_str = sprintf("%02d", hour)
            min_str = sprintf("%02d", min)
            sec_str = sprintf("%02d", sec)
            day_str = sprintf("%02d", day)
            
            # Replace in original line
            new_timestamp = year "-" month "-" day_str " " hour_str ":" min_str ":" sec_str
            gsub(date, new_timestamp)
        }
        print
    }'
}

echo "==================================================================="
echo "ALERT PIPELINE DEBUG for $SYMBOL (last ${WINDOW_MIN}m)"
echo "All timestamps shown in Bali time (UTC+8)"
echo "==================================================================="
echo ""

# Section 1: Strategy (DEBUG_STRATEGY_FINAL)
echo "==================================================================="
echo "STRATEGY: DEBUG_STRATEGY_FINAL for $SYMBOL (last ${WINDOW_MIN}m)"
echo "==================================================================="
ssh hilovivo-aws 'cd /home/ubuntu/automated-trading-platform && docker compose logs backend-aws --since='"${WINDOW_MIN}"'m 2>&1 | grep "'"$SYMBOL"'" | grep DEBUG_STRATEGY_FINAL | tail -n 50' | convert_to_bali_time || echo "(No strategy logs found)"
echo ""

# Section 2: SignalMonitor
echo "==================================================================="
echo "SIGNAL MONITOR for $SYMBOL (last ${WINDOW_MIN}m)"
echo "==================================================================="
ssh hilovivo-aws 'cd /home/ubuntu/automated-trading-platform && docker compose logs backend-aws --since='"${WINDOW_MIN}"'m 2>&1 | grep "'"$SYMBOL"'" | grep -E "(SignalMonitor|DEBUG_SIGNAL_MONITOR)" | tail -n 80' | convert_to_bali_time || echo "(No signal monitor logs found)"
echo ""

# Section 3: Alert helper (ALERT_ logs)
echo "==================================================================="
echo "ALERT PIPELINE (ALERT_ logs) for $SYMBOL (last ${WINDOW_MIN}m)"
echo "==================================================================="
ssh hilovivo-aws 'cd /home/ubuntu/automated-trading-platform && docker compose logs backend-aws --since='"${WINDOW_MIN}"'m 2>&1 | grep "'"$SYMBOL"'" | grep ALERT_ | tail -n 80' | convert_to_bali_time || echo "(No alert pipeline logs found)"
echo ""

# Section 4: Telegram logs
echo "==================================================================="
echo "TELEGRAM logs for $SYMBOL (last ${WINDOW_MIN}m)"
echo "==================================================================="
ssh hilovivo-aws 'cd /home/ubuntu/automated-trading-platform && docker compose logs backend-aws --since='"${WINDOW_MIN}"'m 2>&1 | grep "'"$SYMBOL"'" | grep -E "(TELEGRAM_SEND|TELEGRAM_ERROR|TELEGRAM)" | tail -n 80' | convert_to_bali_time || echo "(No Telegram logs found)"
echo ""

echo "==================================================================="
echo "DEBUG COMPLETE"
echo "==================================================================="

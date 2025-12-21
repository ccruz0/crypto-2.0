#!/bin/bash
# Monitor Telegram Alert Logs
# This script monitors the market-updater-aws logs for Telegram-related messages

echo "=========================================="
echo "Monitoring Telegram Alert Logs"
echo "=========================================="
echo ""
echo "Looking for:"
echo "  - [TELEGRAM_INVOKE] - Alert send attempts"
echo "  - [TELEGRAM_GATEKEEPER] - Gatekeeper decisions"
echo "  - [TELEGRAM_BLOCKED] - Blocked messages"
echo "  - [TELEGRAM_SUCCESS] - Successful sends"
echo "  - [TELEGRAM_ERROR] - Errors"
echo ""
echo "Press Ctrl+C to stop monitoring"
echo "=========================================="
echo ""

docker-compose logs -f market-updater-aws | grep --line-buffered -E "TELEGRAM|telegram" | while read line; do
    # Color code different types of messages
    if echo "$line" | grep -q "TELEGRAM_BLOCKED"; then
        echo -e "\033[0;31m$line\033[0m"  # Red for blocked
    elif echo "$line" | grep -q "TELEGRAM_ERROR"; then
        echo -e "\033[0;31m$line\033[0m"  # Red for errors
    elif echo "$line" | grep -q "TELEGRAM_SUCCESS"; then
        echo -e "\033[0;32m$line\033[0m"  # Green for success
    elif echo "$line" | grep -q "TELEGRAM_GATEKEEPER.*ALLOW"; then
        echo -e "\033[0;32m$line\033[0m"  # Green for allowed
    elif echo "$line" | grep -q "TELEGRAM_GATEKEEPER.*BLOCK"; then
        echo -e "\033[0;31m$line\033[0m"  # Red for blocked
    else
        echo "$line"  # Default color for other messages
    fi
done





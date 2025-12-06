#!/usr/bin/env bash
# Quick helper to inspect monitoring API from local backend
# Usage: bash scripts/debug_monitoring_api_local.sh

set -euo pipefail

cd /Users/carloscruz/automated-trading-platform

echo "Fetching /api/monitoring/telegram-messages from local backend..."
echo ""

# Check if jq is available
if command -v jq &> /dev/null; then
    curl -s http://localhost:8000/api/monitoring/telegram-messages | jq '.' | head -n 40
else
    echo "Note: jq not found, showing raw JSON (first 40 lines)"
    curl -s http://localhost:8000/api/monitoring/telegram-messages | head -n 40
fi

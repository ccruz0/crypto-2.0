#!/bin/bash
# Dashboard Health Check Script
# Verifies that dashboard data is loading correctly
# Runs every 20 minutes

set -euo pipefail

# Configuration
API_URL="${API_URL:-http://localhost:8002/api}"
TIMEOUT=30
MIN_COINS=5
LOG_FILE="${LOG_FILE:-/tmp/dashboard_health_check.log}"
TELEGRAM_BOT_TOKEN="${TELEGRAM_BOT_TOKEN:-}"
TELEGRAM_CHAT_ID="${TELEGRAM_CHAT_ID:-}"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Logging function
log() {
    local level=$1
    shift
    local message="$@"
    local timestamp=$(date '+%Y-%m-%d %H:%M:%S')
    echo -e "[$timestamp] [$level] $message" | tee -a "$LOG_FILE" >&2
}

# Send Telegram notification
send_telegram() {
    local message="$1"
    if [[ -n "$TELEGRAM_BOT_TOKEN" && -n "$TELEGRAM_CHAT_ID" ]]; then
        curl -s -X POST "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
            -d "chat_id=${TELEGRAM_CHAT_ID}" \
            -d "text=${message}" \
            -d "parse_mode=HTML" > /dev/null 2>&1 || true
    fi
}

# Check endpoint
check_endpoint() {
    local endpoint="$1"
    local url="${API_URL}${endpoint}"
    
    log "INFO" "Checking endpoint: $url"
    
    # Make request with timeout
    local response=$(curl -s -m "$TIMEOUT" "$url" 2>&1)
    local exit_code=$?
    
    if [[ $exit_code -ne 0 ]]; then
        log "ERROR" "Failed to connect to $url (exit code: $exit_code)"
        echo "$response"
        return 1
    fi
    
    # Check if response is valid JSON (try jq first, then python as fallback)
    if command -v jq > /dev/null 2>&1; then
        if ! echo "$response" | jq -e . > /dev/null 2>&1; then
            log "ERROR" "Invalid JSON response from $url"
            echo "$response" | head -c 500
            return 1
        fi
    elif command -v python3 > /dev/null 2>&1; then
        if ! echo "$response" | python3 -m json.tool > /dev/null 2>&1; then
            log "ERROR" "Invalid JSON response from $url"
            echo "$response" | head -c 500
            return 1
        fi
    else
        log "WARN" "No JSON parser available (jq or python3), skipping validation"
    fi
    
    echo "$response"
    return 0
}

# Main check function
main() {
    log "INFO" "Starting dashboard health check..."
    
    # Check top-coins-data endpoint
    local response=$(check_endpoint "/market/top-coins-data")
    if [[ $? -ne 0 ]]; then
        local error_msg="❌ <b>Dashboard Health Check Failed</b>

🔴 <b>Endpoint:</b> /api/market/top-coins-data
❌ <b>Error:</b> Failed to connect or invalid response
⏰ <b>Time:</b> $(date '+%Y-%m-%d %H:%M:%S')"
        send_telegram "$error_msg"
        exit 1
    fi
    
    # Parse response (use jq if available, otherwise python)
    local count="0"
    local source="unknown"
    local coins="[]"
    
    if command -v jq > /dev/null 2>&1; then
        count=$(echo "$response" | jq -r '.count // 0' 2>/dev/null || echo "0")
        source=$(echo "$response" | jq -r '.source // "unknown"' 2>/dev/null || echo "unknown")
        coins=$(echo "$response" | jq -c '.coins // []' 2>/dev/null || echo "[]")
    elif command -v python3 > /dev/null 2>&1; then
        count=$(echo "$response" | python3 -c "import sys, json; d=json.load(sys.stdin); print(d.get('count', 0))" 2>/dev/null || echo "0")
        source=$(echo "$response" | python3 -c "import sys, json; d=json.load(sys.stdin); print(d.get('source', 'unknown'))" 2>/dev/null || echo "unknown")
        coins=$(echo "$response" | python3 -c "import sys, json; d=json.load(sys.stdin); import json as j; print(j.dumps(d.get('coins', [])))" 2>/dev/null || echo "[]")
    else
        log "ERROR" "No JSON parser available (jq or python3)"
        return 1
    fi
    
    # Check if we have enough coins
    if [[ "$count" -lt "$MIN_COINS" ]]; then
        local error_msg="❌ <b>Dashboard Health Check Failed</b>

🔴 <b>Endpoint:</b> /api/market/top-coins-data
⚠️ <b>Issue:</b> Insufficient coins (found: $count, minimum: $MIN_COINS)
📊 <b>Source:</b> $source
⏰ <b>Time:</b> $(date '+%Y-%m-%d %H:%M:%S')"
        send_telegram "$error_msg"
        log "ERROR" "Insufficient coins: $count < $MIN_COINS"
        exit 1
    fi
    
    # Check data quality - verify first few coins have required fields
    local missing_fields=0
    local coins_with_data=0
    
    # Parse coins array
    if command -v jq > /dev/null 2>&1; then
        local coin_count=$(echo "$coins" | jq 'length' 2>/dev/null || echo "0")
        for i in $(seq 0 $((coin_count - 1))); do
            [[ $i -ge $MIN_COINS ]] && break
            
            local coin=$(echo "$coins" | jq -c ".[$i]" 2>/dev/null)
            if [[ -z "$coin" || "$coin" == "null" ]]; then
                continue
            fi
            
            local instrument_name=$(echo "$coin" | jq -r '.instrument_name // ""' 2>/dev/null)
            local current_price=$(echo "$coin" | jq -r '.current_price // null' 2>/dev/null)
            
            if [[ -z "$instrument_name" ]]; then
                ((missing_fields++))
                continue
            fi
            
            # Check if price is valid (not null and > 0)
            if [[ "$current_price" == "null" || -z "$current_price" ]]; then
                log "WARN" "Coin $instrument_name has null price"
                ((missing_fields++))
            elif [[ $(echo "$current_price" | awk '{if ($1 <= 0) print "0"; else print "1"}') == "0" ]]; then
                log "WARN" "Coin $instrument_name has invalid price: $current_price"
                ((missing_fields++))
            else
                ((coins_with_data++))
            fi
        done
    elif command -v python3 > /dev/null 2>&1; then
        local coin_count=$(echo "$coins" | python3 -c "import sys, json; print(len(json.load(sys.stdin)))" 2>/dev/null || echo "0")
        for i in $(seq 0 $((coin_count - 1))); do
            [[ $i -ge $MIN_COINS ]] && break
            
            local coin_data=$(echo "$coins" | python3 -c "import sys, json; coins=json.load(sys.stdin); print(json.dumps(coins[$i]) if $i < len(coins) else 'null')" 2>/dev/null)
            if [[ "$coin_data" == "null" || -z "$coin_data" ]]; then
                continue
            fi
            
            local instrument_name=$(echo "$coin_data" | python3 -c "import sys, json; print(json.load(sys.stdin).get('instrument_name', ''))" 2>/dev/null)
            local current_price=$(echo "$coin_data" | python3 -c "import sys, json; d=json.load(sys.stdin); p=d.get('current_price'); print('null' if p is None or p == 0 else str(p))" 2>/dev/null)
            
            if [[ -z "$instrument_name" ]]; then
                ((missing_fields++))
                continue
            fi
            
            if [[ "$current_price" == "null" || -z "$current_price" ]]; then
                log "WARN" "Coin $instrument_name has null price"
                ((missing_fields++))
            else
                ((coins_with_data++))
            fi
        done
    fi
    
    # If too many coins are missing data, alert
    if [[ $coins_with_data -lt $MIN_COINS ]]; then
        local error_msg="❌ <b>Dashboard Health Check Failed</b>

🔴 <b>Endpoint:</b> /api/market/top-coins-data
⚠️ <b>Issue:</b> Data quality issue (only $coins_with_data/$count coins have valid prices)
📊 <b>Source:</b> $source
⏰ <b>Time:</b> $(date '+%Y-%m-%d %H:%M:%S')"
        send_telegram "$error_msg"
        log "ERROR" "Data quality issue: only $coins_with_data/$count coins have valid prices"
        exit 1
    fi
    
    # Success
    log "INFO" "✅ Dashboard health check passed: $count coins from $source (${coins_with_data} with valid data)"
    
    # Send success notification only once per hour (to avoid spam)
    local last_success_file="/tmp/dashboard_health_check_last_success"
    local last_success=$(cat "$last_success_file" 2>/dev/null || echo "0")
    local current_time=$(date +%s)
    local time_since_last_success=$((current_time - last_success))
    
    if [[ $time_since_last_success -gt 3600 ]]; then
        local success_msg="✅ <b>Dashboard Health Check Passed</b>

📊 <b>Coins:</b> $count
✅ <b>Valid Data:</b> $coins_with_data
📈 <b>Source:</b> $source
⏰ <b>Time:</b> $(date '+%Y-%m-%d %H:%M:%S')"
        send_telegram "$success_msg"
        echo "$current_time" > "$last_success_file"
    fi
    
    exit 0
}

# Run main function
main "$@"


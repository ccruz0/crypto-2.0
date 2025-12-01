#!/usr/bin/env bash
#
# Remote debug strategy script
# Runs debug_strategy.py inside the backend container on the remote server via SSH
#
# Usage:
#   bash scripts/debug_strategy_remote.sh [SYMBOL] [LAST_N]
#   bash scripts/debug_strategy_remote.sh ALGO_USDT 20
#   bash scripts/debug_strategy_remote.sh BTC_USDT 50
#

set -e  # Exit on error

# ============================================================================
# CONFIGURATION - EDIT THESE VALUES FOR YOUR SETUP
# ============================================================================

REMOTE_USER="ubuntu"
REMOTE_HOST="hilovivo-aws"
REMOTE_PROJECT_DIR="/home/ubuntu/automated-trading-platform"
BACKEND_SERVICE_NAME="backend-aws"

# ============================================================================
# VALIDATION
# ============================================================================

if [[ "$REMOTE_HOST" == "REPLACE_ME" ]]; then
    echo "❌ ERROR: REMOTE_HOST is not configured!" >&2
    echo "   Please edit this script and set REMOTE_HOST to your server's IP or hostname." >&2
    exit 1
fi

# ============================================================================
# ARGUMENT PARSING
# ============================================================================

SYMBOL="${1:-ALGO_USDT}"
LAST_N="${2:-20}"

# Validate LAST_N is a number
if ! [[ "$LAST_N" =~ ^[0-9]+$ ]]; then
    echo "❌ ERROR: LAST_N must be a number, got: $LAST_N" >&2
    exit 1
fi

# ============================================================================
# BUILD REMOTE COMMAND
# ============================================================================

# Full remote command: cd to project dir, then run debug script on host
# Script reads docker logs, so it runs on host (not inside container)
# Use container name directly (automated-trading-platform-backend-aws-1)
REMOTE_CMD="cd \"$REMOTE_PROJECT_DIR\" && python3 backend/scripts/debug_strategy.py \"$SYMBOL\" --compare --last \"$LAST_N\" --container automated-trading-platform-backend-aws-1"

# ============================================================================
# EXECUTION
# ============================================================================

echo "[REMOTE DEBUG] Running on $REMOTE_USER@$REMOTE_HOST"
echo "[REMOTE DEBUG] Symbol: $SYMBOL"
echo "[REMOTE DEBUG] Last N: $LAST_N"
echo "[REMOTE DEBUG] Command: $REMOTE_CMD"
echo ""

# Execute via SSH
ssh "$REMOTE_USER@$REMOTE_HOST" "$REMOTE_CMD"

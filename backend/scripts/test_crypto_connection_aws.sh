#!/bin/bash
# Test Crypto.com connection for AWS - runs directly on server via SSH
# Usage: ssh to AWS server, then run: bash test_crypto_connection_aws.sh

set -e

echo "============================================================"
echo "🔗 CRYPTO.COM CONNECTION TEST - AWS DIRECT"
echo "============================================================"

# Find backend directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$(dirname "$SCRIPT_DIR")"
PROJECT_ROOT="$(dirname "$BACKEND_DIR")"

# Load environment variables
ENV_FILES=(
    "$PROJECT_ROOT/.env.local"
    "$PROJECT_ROOT/.env"
    "$HOME/.env.local"
    "/opt/automated-trading-platform/.env.local"
    "/home/ubuntu/automated-trading-platform/.env.local"
)

ENV_FILE=""
for file in "${ENV_FILES[@]}"; do
    if [ -f "$file" ]; then
        ENV_FILE="$file"
        break
    fi
done

if [ -n "$ENV_FILE" ]; then
    set -a
    source "$ENV_FILE"
    set +a
fi

# Set LIVE_TRADING if not set
export LIVE_TRADING="${LIVE_TRADING:-true}"

# Check Python
if ! command -v python3 &> /dev/null; then
    echo "❌ ERROR: python3 not found"
    exit 1
fi

# Run the test script
echo ""
echo "🚀 Running connection test..."
echo ""

cd "$BACKEND_DIR"
python3 scripts/test_crypto_connection.py


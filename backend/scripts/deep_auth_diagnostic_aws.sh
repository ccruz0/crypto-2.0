#!/bin/bash
# Deep authentication diagnostic for AWS - runs directly on server via SSH
# Usage: ssh to AWS server, then run: bash deep_auth_diagnostic_aws.sh

set -e

echo "============================================================"
echo "🔍 DEEP AUTHENTICATION DIAGNOSTIC - AWS DIRECT"
echo "============================================================"

# Find backend directory (assuming script is in backend/scripts/)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$(dirname "$SCRIPT_DIR")"
PROJECT_ROOT="$(dirname "$BACKEND_DIR")"

echo "📁 Script directory: $SCRIPT_DIR"
echo "📁 Backend directory: $BACKEND_DIR"
echo "📁 Project root: $PROJECT_ROOT"

# Check if we're in the right location
if [ ! -f "$BACKEND_DIR/app/services/brokers/crypto_com_trade.py" ]; then
    echo "❌ ERROR: Cannot find backend code"
    echo "   Expected: $BACKEND_DIR/app/services/brokers/crypto_com_trade.py"
    echo "   Please run this script from the backend/scripts/ directory"
    exit 1
fi

# Load environment variables
# Try multiple common locations
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
        echo "✅ Found environment file: $ENV_FILE"
        break
    fi
done

if [ -z "$ENV_FILE" ]; then
    echo "⚠️  No .env file found, using environment variables"
    echo "   Make sure EXCHANGE_CUSTOM_API_KEY and EXCHANGE_CUSTOM_API_SECRET are set"
else
    # Load environment variables
    set -a
    source "$ENV_FILE"
    set +a
    echo "✅ Loaded environment variables from $ENV_FILE"
fi

# Check Python
if ! command -v python3 &> /dev/null; then
    echo "❌ ERROR: python3 not found"
    exit 1
fi

PYTHON_VERSION=$(python3 --version)
echo "✅ Python: $PYTHON_VERSION"

# Check required packages
echo ""
echo "📦 Checking required packages..."
python3 -c "import requests, hmac, hashlib, json" 2>/dev/null || {
    echo "❌ ERROR: Missing required packages"
    echo "   Install with: pip3 install requests"
    exit 1
}
echo "✅ Required packages available"

# Run the diagnostic script
echo ""
echo "🚀 Running deep authentication diagnostic..."
echo ""

cd "$BACKEND_DIR"
python3 scripts/deep_auth_diagnostic.py


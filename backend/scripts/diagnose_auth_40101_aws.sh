#!/bin/bash
# Comprehensive authentication diagnostic for AWS - runs directly on server via SSH
# Usage: ssh to AWS server, then run: bash diagnose_auth_40101_aws.sh

set -e

echo "============================================================"
echo "🔍 COMPREHENSIVE AUTHENTICATION DIAGNOSTIC - AWS DIRECT"
echo "============================================================"

# Find backend directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$(dirname "$SCRIPT_DIR")"
PROJECT_ROOT="$(dirname "$BACKEND_DIR")"

echo "📁 Script directory: $SCRIPT_DIR"
echo "📁 Backend directory: $BACKEND_DIR"

# Check if we're in the right location
if [ ! -f "$BACKEND_DIR/app/services/brokers/crypto_com_trade.py" ]; then
    echo "❌ ERROR: Cannot find backend code"
    echo "   Expected: $BACKEND_DIR/app/services/brokers/crypto_com_trade.py"
    exit 1
fi

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
        echo "✅ Found environment file: $ENV_FILE"
        break
    fi
done

if [ -z "$ENV_FILE" ]; then
    echo "⚠️  No .env file found, using environment variables"
else
    set -a
    source "$ENV_FILE"
    set +a
    echo "✅ Loaded environment variables"
fi

# Check Python
if ! command -v python3 &> /dev/null; then
    echo "❌ ERROR: python3 not found"
    exit 1
fi

# Run the diagnostic script
echo ""
echo "🚀 Running comprehensive diagnostic..."
echo ""

cd "$BACKEND_DIR"
python3 scripts/diagnose_auth_40101.py


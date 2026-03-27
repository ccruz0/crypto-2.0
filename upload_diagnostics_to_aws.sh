#!/bin/bash
# Upload diagnostic scripts to AWS server
# Usage: ./upload_diagnostics_to_aws.sh

set -e

AWS_SERVER="ubuntu@47.130.143.159"
REMOTE_PATH="~/crypto-2.0/backend/scripts"

echo "============================================================"
echo "📤 Uploading Diagnostic Scripts to AWS"
echo "============================================================"

# Check if scripts exist locally
SCRIPT_DIR="backend/scripts"
if [ ! -d "$SCRIPT_DIR" ]; then
    echo "❌ ERROR: backend/scripts directory not found"
    echo "   Run this script from the project root"
    exit 1
fi

echo ""
echo "📁 Uploading scripts..."

# Upload diagnostic scripts
rsync -avz --progress \
    "$SCRIPT_DIR/test_script_works.py" \
    "$SCRIPT_DIR/deep_auth_diagnostic.py" \
    "$SCRIPT_DIR/diagnose_auth_40101.py" \
    "$SCRIPT_DIR/test_crypto_connection.py" \
    "$SCRIPT_DIR/verify_api_key_setup.py" \
    "$AWS_SERVER:$REMOTE_PATH/"

echo ""
echo "✅ Scripts uploaded successfully!"
echo ""
echo "💡 Now you can run:"
echo "   ssh $AWS_SERVER \"cd ~/crypto-2.0/backend && python3 scripts/test_script_works.py\""
echo ""


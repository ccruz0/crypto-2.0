#!/bin/bash
# Quick script to diagnose and fix authentication issues on AWS
# Run this on your AWS server: ssh hilovivo-aws "bash -s" < fix_auth_on_aws.sh

set -e

echo "============================================================"
echo "🔍 CRYPTO.COM AUTHENTICATION DIAGNOSTIC & FIX"
echo "============================================================"
echo ""

# Step 1: Get current IP
echo "📋 Step 1: Getting current AWS IP address..."
echo "------------------------------------------------------------"
cd ~/automated-trading-platform
docker compose --profile aws exec backend-aws python scripts/get_aws_ip.py
echo ""

# Step 2: Check configuration
echo "📋 Step 2: Checking API credentials configuration..."
echo "------------------------------------------------------------"
docker compose --profile aws exec backend-aws python scripts/check_crypto_config.py
echo ""

# Step 3: Run full diagnostic
echo "📋 Step 3: Running full authentication diagnostic..."
echo "------------------------------------------------------------"
docker compose --profile aws exec backend-aws python scripts/diagnose_auth_issue.py
echo ""

# Step 4: Test connection
echo "📋 Step 4: Testing Crypto.com connection..."
echo "------------------------------------------------------------"
docker compose --profile aws exec backend-aws python scripts/test_crypto_connection.py
echo ""

echo "============================================================"
echo "✅ DIAGNOSTIC COMPLETE"
echo "============================================================"
echo ""
echo "📝 Next Steps:"
echo "1. Review the diagnostic output above"
echo "2. Fix any issues identified (IP whitelist, credentials, etc.)"
echo "3. Restart backend: docker compose --profile aws restart backend-aws"
echo "4. Monitor logs: docker compose --profile aws logs -f backend-aws | grep -i auth"
echo ""


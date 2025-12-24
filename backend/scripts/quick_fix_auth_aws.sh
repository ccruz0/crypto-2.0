#!/bin/bash
# Quick fix script for authentication issues on AWS
# This script helps you quickly diagnose and fix Crypto.com Exchange API authentication

set -e

echo "================================================================================"
echo "🔐 CRYPTO.COM EXCHANGE API - QUICK FIX FOR AWS"
echo "================================================================================"
echo ""

# Step 1: Get server IP
echo "📡 Step 1: Getting your server's IP address..."
SERVER_IP=$(curl -s https://api.ipify.org)
echo "   Your server IP: $SERVER_IP"
echo ""
echo "⚠️  IMPORTANT: This IP must be whitelisted in Crypto.com Exchange!"
echo ""

# Step 2: Check credentials
echo "🔑 Step 2: Checking API credentials..."
if [ -z "$EXCHANGE_CUSTOM_API_KEY" ] || [ -z "$EXCHANGE_CUSTOM_API_SECRET" ]; then
    echo "   ❌ ERROR: API credentials are not set!"
    echo ""
    echo "   To fix this, set the following environment variables:"
    echo "   export EXCHANGE_CUSTOM_API_KEY='your_api_key'"
    echo "   export EXCHANGE_CUSTOM_API_SECRET='your_api_secret'"
    echo ""
    echo "   Or add them to your .env.aws file:"
    echo "   EXCHANGE_CUSTOM_API_KEY=your_api_key"
    echo "   EXCHANGE_CUSTOM_API_SECRET=your_api_secret"
    echo ""
    exit 1
else
    API_KEY_PREVIEW="${EXCHANGE_CUSTOM_API_KEY:0:4}....${EXCHANGE_CUSTOM_API_KEY: -4}"
    echo "   ✅ API Key: $API_KEY_PREVIEW"
    echo "   ✅ API Secret: <SET>"
fi
echo ""

# Step 3: Check if using proxy
echo "🔄 Step 3: Checking connection method..."
if [ "$USE_CRYPTO_PROXY" = "true" ]; then
    echo "   Using PROXY: $CRYPTO_PROXY_URL"
    echo "   ⚠️  If authentication fails, check that the proxy service is running"
else
    echo "   Using DIRECT connection"
    echo "   ⚠️  Make sure IP $SERVER_IP is whitelisted in Crypto.com Exchange"
fi
echo ""

# Step 4: Run diagnostic
echo "🔍 Step 4: Running authentication diagnostic..."
echo ""
python3 backend/scripts/diagnose_auth_issue.py
DIAG_RESULT=$?

echo ""
echo "================================================================================"
if [ $DIAG_RESULT -eq 0 ]; then
    echo "✅ DIAGNOSTIC COMPLETE - Authentication appears to be working"
    echo ""
    echo "If you're still seeing authentication errors:"
    echo "1. Restart the backend service: docker compose restart backend"
    echo "2. Check logs: docker compose logs backend -f | grep -i auth"
else
    echo "❌ DIAGNOSTIC FOUND ISSUES - Follow the recommendations above"
    echo ""
    echo "QUICK FIX CHECKLIST:"
    echo "□ 1. Verify API key and secret are correct"
    echo "□ 2. Add IP $SERVER_IP to Crypto.com Exchange API key whitelist"
    echo "□ 3. Ensure API key has 'Trade' permission enabled"
    echo "□ 4. Check if API key is active (not expired/revoked)"
    echo "□ 5. Wait 2-5 minutes after updating IP whitelist"
    echo "□ 6. Restart backend: docker compose restart backend"
    echo ""
    echo "For detailed instructions, see: AUTHENTICATION_TROUBLESHOOTING.md"
fi
echo "================================================================================"


#!/bin/bash
# Verify AWS backend credentials configuration

echo "=== AWS Backend Credentials Verification ==="
echo ""

# Check .env.aws file
if [ -f .env.aws ]; then
    echo "✅ .env.aws file exists"
    
    # Check for required variables
    if grep -q "EXCHANGE_CUSTOM_API_KEY" .env.aws; then
        echo "✅ EXCHANGE_CUSTOM_API_KEY found in .env.aws"
    else
        echo "❌ EXCHANGE_CUSTOM_API_KEY missing in .env.aws"
    fi
    
    if grep -q "EXCHANGE_CUSTOM_API_SECRET" .env.aws; then
        echo "✅ EXCHANGE_CUSTOM_API_SECRET found in .env.aws"
    else
        echo "❌ EXCHANGE_CUSTOM_API_SECRET missing in .env.aws"
    fi
    
    if grep -q "USE_CRYPTO_PROXY=false" .env.aws; then
        echo "✅ USE_CRYPTO_PROXY=false (direct connection)"
    else
        echo "⚠️  USE_CRYPTO_PROXY not set to false"
    fi
    
    if grep -q "LIVE_TRADING=true" .env.aws; then
        echo "✅ LIVE_TRADING=true"
    else
        echo "⚠️  LIVE_TRADING not set to true"
    fi
else
    echo "❌ .env.aws file not found"
fi

echo ""
echo "=== Docker Compose AWS Profile ==="
if docker compose --profile aws config > /dev/null 2>&1; then
    echo "✅ Docker Compose AWS profile is valid"
else
    echo "❌ Docker Compose AWS profile has errors"
fi

echo ""
echo "=== Expected Behavior ==="
echo "✅ On AWS: Credentials will work (IP 47.130.143.159 whitelisted)"
echo "❌ Locally: Authentication will fail (IP not whitelisted - expected)"

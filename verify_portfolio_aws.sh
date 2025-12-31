#!/bin/bash
# End-to-end portfolio verification on AWS
# Returns PASS/FAIL with exact diff in USD

set -e

DIAGNOSTICS_API_KEY="${DIAGNOSTICS_API_KEY:-eJrAlyoA9SleEMAwRpvISw5qekXAfFoTVMxB6Ja-TUA}"
AWS_HOST="${AWS_HOST:-hilovivo-aws}"
REPO_PATH="/home/ubuntu/automated-trading-platform"
BACKEND_PORT="8002"

echo "🔍 Verifying portfolio on AWS..."
echo ""

# Step 1: Add env vars to .env.aws if not present
echo "📝 Step 1: Ensuring diagnostics env vars are set..."
ssh "$AWS_HOST" "cd $REPO_PATH && \
  if ! grep -q 'ENABLE_DIAGNOSTICS_ENDPOINTS' .env.aws 2>/dev/null; then
    echo 'ENABLE_DIAGNOSTICS_ENDPOINTS=1' >> .env.aws
    echo '✅ Added ENABLE_DIAGNOSTICS_ENDPOINTS=1'
  else
    echo '✅ ENABLE_DIAGNOSTICS_ENDPOINTS already set'
  fi && \
  if ! grep -q '^DIAGNOSTICS_API_KEY=' .env.aws 2>/dev/null; then
    echo \"DIAGNOSTICS_API_KEY=$DIAGNOSTICS_API_KEY\" >> .env.aws
    echo '✅ Added DIAGNOSTICS_API_KEY'
  else
    echo '✅ DIAGNOSTICS_API_KEY already set'
  fi"

# Step 2: Restart backend-aws to load env vars
echo ""
echo "🔄 Step 2: Restarting backend-aws to load env vars..."
ssh "$AWS_HOST" "cd $REPO_PATH && \
  sudo bash -lc \"export ENABLE_DIAGNOSTICS_ENDPOINTS=1 DIAGNOSTICS_API_KEY='$DIAGNOSTICS_API_KEY' && \
  docker compose --profile aws restart backend-aws\""

# Step 3: Wait for backend to be healthy
echo ""
echo "⏳ Step 3: Waiting for backend to be healthy..."
sleep 10
for i in {1..30}; do
  if ssh "$AWS_HOST" "curl -s -f http://localhost:$BACKEND_PORT/ping_fast > /dev/null 2>&1"; then
    echo "✅ Backend is healthy"
    break
  fi
  if [ $i -eq 30 ]; then
    echo "❌ Backend did not become healthy after 30 attempts"
    exit 1
  fi
  sleep 2
done

# Step 4: Run verification endpoint
echo ""
echo "🔍 Step 4: Running portfolio verification..."
RESULT=$(ssh "$AWS_HOST" "cd $REPO_PATH && \
  curl -s -H \"X-Diagnostics-Key: $DIAGNOSTICS_API_KEY\" \
  http://localhost:$BACKEND_PORT/api/diagnostics/portfolio-verify-lite")

# Step 5: Parse and display results
echo ""
echo "📊 Verification Results:"
echo "$RESULT" | jq '.'

PASS=$(echo "$RESULT" | jq -r '.pass // false')
DASHBOARD_NET=$(echo "$RESULT" | jq -r '.dashboard_net_usd // 0')
CRYPTO_COM_NET=$(echo "$RESULT" | jq -r '.crypto_com_net_usd // 0')
DIFF_USD=$(echo "$RESULT" | jq -r '.diff_usd // 0')

echo ""
echo "=========================================="
if [ "$PASS" = "true" ]; then
  echo "✅ PASS"
else
  echo "❌ FAIL"
fi
echo "Dashboard NET:  \$$(printf '%.2f' $DASHBOARD_NET)"
echo "Crypto.com NET: \$$(printf '%.2f' $CRYPTO_COM_NET)"
echo "Difference:     \$$(printf '%.2f' $DIFF_USD)"
echo "=========================================="

# Exit with appropriate code
if [ "$PASS" = "true" ]; then
  exit 0
else
  exit 1
fi


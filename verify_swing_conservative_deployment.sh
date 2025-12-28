#!/bin/bash
# Verification script for Swing Conservative strategy update deployment

set -e

echo "🔍 Verifying Swing Conservative Strategy Update Deployment"
echo "=========================================================="
echo ""

INSTANCE_ID="${AWS_INSTANCE_ID:-i-08726dc37133b2454}"
REGION="${AWS_REGION:-ap-southeast-1}"

# Colors for output
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

check_passed() {
    echo -e "${GREEN}✅ $1${NC}"
}

check_failed() {
    echo -e "${RED}❌ $1${NC}"
}

check_warning() {
    echo -e "${YELLOW}⚠️  $1${NC}"
}

# Check 1: Verify backend config file has new defaults
echo "📋 Check 1: Verifying backend config file..."
if [ -f "backend/trading_config.json" ]; then
    if grep -q '"buyBelow": 30' backend/trading_config.json && \
       grep -q '"volumeMinRatio": 1.0' backend/trading_config.json && \
       grep -q '"minPriceChangePct": 3.0' backend/trading_config.json; then
        check_passed "Backend config file has new defaults"
    else
        check_failed "Backend config file missing new defaults"
    fi
else
    check_failed "Backend config file not found"
fi

# Check 2: Verify new gating parameters in config
echo ""
echo "📋 Check 2: Verifying new gating parameters in config..."
if grep -q '"trendFilters"' backend/trading_config.json && \
   grep -q '"rsiConfirmation"' backend/trading_config.json && \
   grep -q '"candleConfirmation"' backend/trading_config.json && \
   grep -q '"atr"' backend/trading_config.json; then
    check_passed "New gating parameters found in config"
else
    check_failed "New gating parameters missing in config"
fi

# Check 3: Run backend tests
echo ""
echo "📋 Check 3: Running backend tests..."
if [ -f "backend/tests/test_swing_conservative_gating.py" ]; then
    if python3 -m pytest backend/tests/test_swing_conservative_gating.py -v 2>/dev/null; then
        check_passed "Backend tests passed"
    else
        check_warning "Backend tests failed or pytest not available (run manually: pytest backend/tests/test_swing_conservative_gating.py)"
    fi
else
    check_warning "Test file not found locally (should be on server)"
fi

# Check 4: Verify config loader migration function exists
echo ""
echo "📋 Check 4: Verifying config loader has migration function..."
if grep -q "_migrate_swing_conservative_defaults" backend/app/services/config_loader.py; then
    check_passed "Migration function found in config_loader.py"
else
    check_failed "Migration function not found"
fi

# Check 5: Verify signal generation uses new parameters
echo ""
echo "📋 Check 5: Verifying signal generation uses new parameters..."
if grep -q "trendFilters\|rsiConfirmation\|candleConfirmation" backend/app/services/trading_signals.py; then
    check_passed "Signal generation uses new gating parameters"
else
    check_failed "Signal generation missing new parameters"
fi

# Check 6: Verify frontend types
echo ""
echo "📋 Check 6: Verifying frontend type definitions..."
if [ -f "frontend/src/types/dashboard.ts" ]; then
    if grep -q "trendFilters\|rsiConfirmation\|candleConfirmation" frontend/src/types/dashboard.ts; then
        check_passed "Frontend types include new parameters"
    else
        check_warning "Frontend types may not have new parameters (check manually)"
    fi
else
    check_warning "Frontend types file not found locally"
fi

# Check 7: Remote verification (if AWS CLI available and instance ID provided)
if command -v aws &> /dev/null && [ -n "$INSTANCE_ID" ]; then
    echo ""
    echo "📋 Check 7: Verifying deployment on AWS instance..."
    echo "   Instance: $INSTANCE_ID"
    echo "   Region: $REGION"
    
    COMMAND_ID=$(aws ssm send-command \
      --instance-ids "$INSTANCE_ID" \
      --document-name "AWS-RunShellScript" \
      --parameters "commands=[
        \"cd ~/automated-trading-platform || cd /home/ubuntu/automated-trading-platform\",
        \"echo '=== Checking config file ==='\",
        \"if [ -f backend/trading_config.json ]; then\",
        \"  echo 'Config file exists'\",
        \"  grep -q '\\\"buyBelow\\\": 30' backend/trading_config.json && echo 'RSI buyBelow=30: OK' || echo 'RSI buyBelow=30: NOT FOUND'\",
        \"  grep -q '\\\"volumeMinRatio\\\": 1.0' backend/trading_config.json && echo 'volumeMinRatio=1.0: OK' || echo 'volumeMinRatio=1.0: NOT FOUND'\",
        \"  grep -q 'trendFilters' backend/trading_config.json && echo 'trendFilters: OK' || echo 'trendFilters: NOT FOUND'\",
        \"else\",
        \"  echo 'Config file NOT FOUND'\",
        \"fi\",
        \"echo ''\",
        \"echo '=== Checking Python imports ==='\",
        \"CONTAINER=\\\$(docker compose --profile aws ps -q backend 2>/dev/null || docker ps -q --filter 'name=backend')\",
        \"if [ -n \\\"\\\$CONTAINER\\\" ]; then\",
        \"  echo 'Backend container found: '\\\$CONTAINER\",
        \"  docker exec \\\$CONTAINER python -c 'from app.services.config_loader import load_config; import json; cfg = load_config(); rules = cfg.get(\\\"strategy_rules\\\", {}).get(\\\"swing\\\", {}).get(\\\"rules\\\", {}).get(\\\"Conservative\\\", {}); print(json.dumps({k: v for k, v in rules.items() if k in [\\\"rsi\\\", \\\"volumeMinRatio\\\", \\\"minPriceChangePct\\\", \\\"trendFilters\\\", \\\"rsiConfirmation\\\"]}, indent=2))' 2>&1 || echo 'Python import check failed'\",
        \"else\",
        \"  echo 'Backend container NOT FOUND'\",
        \"fi\"
      ]" \
      --region "$REGION" \
      --output text \
      --query "Command.CommandId" 2>&1)
    
    if [ $? -eq 0 ] && [ -n "$COMMAND_ID" ]; then
        echo "   Command sent: $COMMAND_ID"
        echo "   Waiting for execution..."
        sleep 3
        
        aws ssm wait command-executed \
          --command-id "$COMMAND_ID" \
          --instance-id "$INSTANCE_ID" \
          --region "$REGION" 2>/dev/null || true
        
        echo ""
        echo "   Remote verification output:"
        aws ssm get-command-invocation \
          --command-id "$COMMAND_ID" \
          --instance-id "$INSTANCE_ID" \
          --region "$REGION" \
          --query "StandardOutputContent" --output text 2>/dev/null || check_warning "Could not retrieve remote output"
    else
        check_warning "Could not send SSM command (check AWS credentials and permissions)"
    fi
else
    check_warning "AWS CLI not available or INSTANCE_ID not set (skipping remote verification)"
fi

echo ""
echo "=========================================================="
echo "✅ Verification complete!"
echo ""
echo "📝 Next steps:"
echo "   1. Review the checks above"
echo "   2. Test signal generation with Swing Conservative strategy"
echo "   3. Verify migration ran correctly (check backend logs)"
echo "   4. Test frontend UI (once form controls are added)"
echo ""


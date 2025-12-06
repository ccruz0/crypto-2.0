#!/bin/bash
# Script to check logs for test order issues
# Run this on AWS server: docker compose exec backend-aws bash /app/tools/check_logs.sh

echo "=========================================="
echo "CHECKING LOGS FOR TEST ORDER ISSUES"
echo "=========================================="
echo ""

echo "1. Recent simulate-alert calls:"
echo "----------------------------------------"
docker compose logs backend-aws 2>&1 | grep -i "simulate-alert\|SIMULATING BUY" | tail -20
echo ""

echo "2. Order creation attempts:"
echo "----------------------------------------"
docker compose logs backend-aws 2>&1 | grep -E "(Trade enabled|creating BUY order|ORDER CREATION|_create_buy_order)" | tail -30
echo ""

echo "3. SOL_USDT related logs:"
echo "----------------------------------------"
docker compose logs backend-aws 2>&1 | grep -i "SOL_USDT" | tail -30
echo ""

echo "4. Recent errors:"
echo "----------------------------------------"
docker compose logs backend-aws 2>&1 | grep -iE "(error|exception|failed|traceback)" | grep -iE "(SOL_USDT|order|simulate|test)" | tail -30
echo ""

echo "5. Recent backend logs (last 50 lines):"
echo "----------------------------------------"
docker compose logs backend-aws --tail 50 | grep -iE "(SOL_USDT|simulate|test|order|trade)" 
echo ""

echo "=========================================="
echo "LOG CHECK COMPLETE"
echo "=========================================="


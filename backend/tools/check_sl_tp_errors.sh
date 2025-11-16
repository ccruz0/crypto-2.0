#!/bin/bash
# Script to check SL/TP order creation errors
# Run this on AWS server: docker compose exec backend-aws bash /app/tools/check_sl_tp_errors.sh

echo "=========================================="
echo "CHECKING SL/TP ORDER CREATION ERRORS"
echo "=========================================="
echo ""

ORDER_ID="5755600477880747933"
SYMBOL="SOL_USDT"

echo "1. Recent SL/TP creation attempts:"
echo "----------------------------------------"
docker compose logs backend-aws 2>&1 | grep -E "(Creating SL/TP|SL/TP.*SOL_USDT|create_sl_tp_for_filled_order)" | tail -30
echo ""

echo "2. SL/TP order creation errors:"
echo "----------------------------------------"
docker compose logs backend-aws 2>&1 | grep -E "(SL/TP.*FAILED|Error.*SL|Error.*TP|error.*229|error.*40004|error.*220)" | tail -30
echo ""

echo "3. HTTP logs for SL orders:"
echo "----------------------------------------"
docker compose logs backend-aws 2>&1 | grep -E "\[SL_ORDER\]" | tail -50
echo ""

echo "4. HTTP logs for TP orders:"
echo "----------------------------------------"
docker compose logs backend-aws 2>&1 | grep -E "\[TP_ORDER\]" | tail -50
echo ""

echo "5. Recent errors for $SYMBOL:"
echo "----------------------------------------"
docker compose logs backend-aws 2>&1 | grep -i "$SYMBOL" | grep -iE "(error|exception|failed)" | tail -30
echo ""

echo "6. Full SL/TP creation log context:"
echo "----------------------------------------"
docker compose logs backend-aws 2>&1 | grep -A 20 -B 5 "Creating SL/TP for $SYMBOL order $ORDER_ID" | tail -50
echo ""

echo "=========================================="
echo "LOG CHECK COMPLETE"
echo "=========================================="


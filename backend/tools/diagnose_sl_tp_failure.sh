#!/bin/bash
# Comprehensive diagnostic script for SL/TP order failures
# Usage: docker compose exec backend-aws bash /app/tools/diagnose_sl_tp_failure.sh ORDER_ID SYMBOL

ORDER_ID="${1:-5755600477880747933}"
SYMBOL="${2:-SOL_USDT}"

echo "=========================================="
echo "SL/TP FAILURE DIAGNOSTIC"
echo "=========================================="
echo "Order ID: $ORDER_ID"
echo "Symbol: $SYMBOL"
echo ""

echo "1. SL/TP CREATION ATTEMPT:"
echo "----------------------------------------"
docker compose logs backend-aws 2>&1 | grep -A 30 "Creating SL/TP for $SYMBOL.*$ORDER_ID" | tail -40
echo ""

echo "2. SL ORDER CREATION LOGS:"
echo "----------------------------------------"
docker compose logs backend-aws 2>&1 | grep -E "\[.*SL.*\]|Creating SL order|SL order.*$SYMBOL" | tail -30
echo ""

echo "3. TP ORDER CREATION LOGS:"
echo "----------------------------------------"
docker compose logs backend-aws 2>&1 | grep -E "\[.*TP.*\]|Creating TP order|TP order.*$SYMBOL" | tail -30
echo ""

echo "4. HTTP REQUEST LOGS FOR SL:"
echo "----------------------------------------"
docker compose logs backend-aws 2>&1 | grep "\[SL_ORDER\]" | tail -50
echo ""

echo "5. HTTP REQUEST LOGS FOR TP:"
echo "----------------------------------------"
docker compose logs backend-aws 2>&1 | grep "\[TP_ORDER\]" | tail -50
echo ""

echo "6. ERROR MESSAGES:"
echo "----------------------------------------"
docker compose logs backend-aws 2>&1 | grep -iE "(error|failed|exception|229|40004|220|308)" | grep -iE "$SYMBOL|$ORDER_ID|SL|TP" | tail -40
echo ""

echo "7. DETAILED ERROR LOGS:"
echo "----------------------------------------"
docker compose logs backend-aws 2>&1 | grep -A 10 "❌.*SL.*failed\|❌.*TP.*failed\|BOTH SL/TP orders failed" | tail -50
echo ""

echo "8. PAYLOAD DETAILS:"
echo "----------------------------------------"
docker compose logs backend-aws 2>&1 | grep -E "PAYLOAD DETAILS|FULL PAYLOAD|Payload JSON" | tail -30
echo ""

echo "9. RECENT BACKEND LOGS (last 100 lines filtered):"
echo "----------------------------------------"
docker compose logs backend-aws --tail 200 | grep -iE "$SYMBOL|$ORDER_ID|SL|TP|error" | tail -50
echo ""

echo "=========================================="
echo "DIAGNOSTIC COMPLETE"
echo "=========================================="
echo ""
echo "Next steps:"
echo "1. Look for error codes: 229 (INVALID_REF_PRICE), 40004 (Missing argument), 220 (INVALID_SIDE)"
echo "2. Check if ref_price is being calculated correctly"
echo "3. Verify that side is being inverted correctly (BUY -> SELL for TP/SL)"
echo "4. Check price formatting (decimals, precision)"


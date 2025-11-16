#!/bin/bash
# Script to extract and compare HTTP logs for TP/SL orders
# Usage: ./extract_http_logs.sh [AUTO|MANUAL|BOTH]

SOURCE_FILTER="${1:-BOTH}"

echo "============================================================"
echo "Extracting HTTP logs for TP/SL orders"
echo "Source filter: $SOURCE_FILTER"
echo "============================================================"
echo ""

if [ "$SOURCE_FILTER" = "AUTO" ] || [ "$SOURCE_FILTER" = "BOTH" ]; then
    echo "--- AUTO FLOW LOGS ---"
    docker compose logs backend-aws 2>&1 | grep -E "\[TP_ORDER\]\[AUTO\]|\[SL_ORDER\]\[AUTO\]" | tail -50
    echo ""
fi

if [ "$SOURCE_FILTER" = "MANUAL" ] || [ "$SOURCE_FILTER" = "BOTH" ]; then
    echo "--- MANUAL FLOW LOGS ---"
    docker compose logs backend-aws 2>&1 | grep -E "\[TP_ORDER\]\[MANUAL\]|\[SL_ORDER\]\[MANUAL\]" | tail -50
    echo ""
fi

echo "============================================================"
echo "To extract specific request/response pairs, use:"
echo "  docker compose logs backend-aws 2>&1 | grep 'REQUEST_ID_HERE'"
echo "============================================================"


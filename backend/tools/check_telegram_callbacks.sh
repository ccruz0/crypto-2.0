#!/bin/bash
# Script to check Telegram callback logs

echo "=== Checking Telegram callback logs (last 50 lines) ==="
echo ""
docker compose logs backend-aws 2>&1 | grep -i "TG.*callback\|TG.*Handling\|TG.*ERROR\|TG.*Processing" | tail -50

echo ""
echo "=== Checking for duplicate callbacks ==="
docker compose logs backend-aws 2>&1 | grep -i "Duplicate callback" | tail -10

echo ""
echo "=== Checking for errors ==="
docker compose logs backend-aws 2>&1 | grep -i "TG.*ERROR" | tail -20


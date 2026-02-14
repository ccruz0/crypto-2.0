#!/usr/bin/env bash
# Step D — Verification: prove zombie count stops increasing (run on EC2 after deploy).
# No secrets. Run after applying Python healthcheck fix and recreating backend-aws + market-updater-aws.
# Usage: cd /home/ubuntu/automated-trading-platform && bash scripts/aws/verify_zombie_count_stable.sh
set -euo pipefail

echo "=== Baseline zombie count ==="
ps -eo stat | awk '$1 ~ /Z/ {c++} END{print "zombies:", c+0}'

echo ""
echo "=== Monitor every 60s for 10 minutes ==="
for i in {1..10}; do
  date
  ps -eo stat | awk '$1 ~ /Z/ {c++} END{print "zombies:", c+0}'
  sleep 60
done

echo ""
echo "=== Health check ==="
curl -s -o /dev/null -w "http://127.0.0.1:8002/health -> %{http_code}\n" http://127.0.0.1:8002/health || true
docker compose --profile aws ps 2>/dev/null | sed -n '1,8p' || true

echo ""
echo "=== PASS if: zombie count did not increase each minute; backend-aws and market-updater-aws healthy; /health 200 ==="

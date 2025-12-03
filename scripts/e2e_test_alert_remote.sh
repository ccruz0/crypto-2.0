#!/usr/bin/env bash

set -euo pipefail

cd /Users/carloscruz/automated-trading-platform

echo "=== Triggering E2E test alert on AWS ==="

ssh hilovivo-aws "cd /home/ubuntu/automated-trading-platform && \
  curl -s -X POST http://localhost:8002/api/test/e2e-alert -H 'Content-Type: application/json' || echo 'Request failed'"

echo ""
echo "=== Last 300 backend log lines with E2E_TEST markers ==="

ssh hilovivo-aws "cd /home/ubuntu/automated-trading-platform && \
  docker compose logs backend-aws --tail 300 | grep 'E2E_TEST' || echo 'No E2E_TEST logs found'"



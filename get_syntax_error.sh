#!/bin/bash
cd /home/ubuntu/automated-trading-platform || cd ~/automated-trading-platform
echo "=== Container Status ==="
docker compose --profile aws ps
echo ""
echo "=== Full Backend Logs (last 200 lines) ==="
docker compose --profile aws logs --no-color --tail=200 backend-aws 2>&1

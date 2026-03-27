#!/bin/bash
cd /home/ubuntu/crypto-2.0 || cd ~/crypto-2.0
echo "=== Container Status ==="
docker compose --profile aws ps
echo ""
echo "=== Full Backend Logs (last 200 lines) ==="
docker compose --profile aws logs --no-color --tail=200 backend-aws 2>&1

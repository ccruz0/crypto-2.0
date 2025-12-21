#!/bin/bash
# Final Deployment Script - Run this on AWS server

cd /home/ubuntu/automated-trading-platform

# Step 1: Fix git and pull
export HOME=/home/ubuntu
git config --global --add safe.directory /home/ubuntu/automated-trading-platform 2>/dev/null || true
git pull origin main 2>&1

# Step 2: Find container (try different names)
CONTAINER=$(docker ps --filter "name=market-updater" --format "{{.Names}}" | head -1)

if [ -z "$CONTAINER" ]; then
    echo "Available containers:"
    docker ps --format "{{.Names}}"
    echo ""
    echo "Please manually set CONTAINER variable with the correct container name"
    exit 1
fi

echo "Using container: $CONTAINER"

# Step 3: Copy file
docker cp backend/app/services/signal_monitor.py $CONTAINER:/app/app/services/signal_monitor.py

# Step 4: Verify
docker exec $CONTAINER grep "alert_origin = get_runtime_origin()" /app/app/services/signal_monitor.py && echo "✅ Verified"

# Step 5: Restart
docker compose --profile aws restart market-updater-aws 2>&1 || docker restart $CONTAINER

sleep 5
docker ps --filter "name=market-updater" --format "table {{.Names}}\t{{.Status}}"

echo "✅ Done!"





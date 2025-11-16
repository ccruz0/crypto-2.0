#!/bin/bash
# Monitor backend stability for a few minutes

# Unified SSH
. ./scripts/ssh_key.sh 2>/dev/null || source ./scripts/ssh_key.sh
EC2_HOST="175.41.189.249"
DURATION_MINUTES=3
CHECK_INTERVAL=30  # Check every 30 seconds

echo "🔍 Monitoring backend stability for ${DURATION_MINUTES} minutes..."
echo "Checking every ${CHECK_INTERVAL} seconds..."
echo ""

for i in $(seq 1 $((DURATION_MINUTES * 60 / CHECK_INTERVAL))); do
    timestamp=$(date '+%Y-%m-%d %H:%M:%S')
    echo "[$timestamp] Check #$i:"
    
    # Check backend status
    status=$(ssh_cmd ubuntu@$EC2_HOST \
        "cd ~/automated-trading-platform && docker compose --profile aws ps backend-aws 2>&1 | grep -o 'Up [0-9]*' | head -1" 2>/dev/null)
    
    if [ -z "$status" ]; then
        echo "  ❌ Backend status: UNKNOWN or DOWN"
    else
        echo "  ✅ Backend status: $status"
    fi
    
    # Check alert-ratio requests in last minute
    alert_count=$(ssh_cmd ubuntu@$EC2_HOST \
        "cd ~/automated-trading-platform && docker compose --profile aws logs --since 1m backend-aws 2>&1 | grep -c 'alert-ratio' || echo 0" 2>/dev/null)
    
    echo "  📊 Alert-ratio requests (last minute): $alert_count"
    
    # Check CPU/Memory
    resources=$(ssh_cmd ubuntu@$EC2_HOST \
        "docker stats --no-stream --format '{{.CPUPerc}}\t{{.MemUsage}}' automated-trading-platform-backend-aws-1 2>&1 | tail -1" 2>/dev/null)
    
    if [ ! -z "$resources" ]; then
        echo "  💻 Resources: $resources"
    fi
    
    # Check for errors
    errors=$(ssh_cmd ubuntu@$EC2_HOST \
        "cd ~/automated-trading-platform && docker compose --profile aws logs --since 1m backend-aws 2>&1 | grep -iE 'error|exception|503|died|killed' | wc -l || echo 0" 2>/dev/null)
    
    if [ "$errors" -gt 0 ]; then
        echo "  ⚠️  Errors found (last minute): $errors"
    else
        echo "  ✅ No errors in last minute"
    fi
    
    echo ""
    
    if [ $i -lt $((DURATION_MINUTES * 60 / CHECK_INTERVAL)) ]; then
        sleep $CHECK_INTERVAL
    fi
done

echo "✅ Monitoring complete!"



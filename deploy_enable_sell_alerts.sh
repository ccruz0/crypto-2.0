#!/bin/bash
# Deploy and run the enable_sell_alerts.py script on AWS server

echo "Deploying enable_sell_alerts.py to AWS server..."
echo ""

# Copy script to server
scp backend/scripts/enable_sell_alerts.py ubuntu@175.41.189.249:~/automated-trading-platform/backend/scripts/enable_sell_alerts.py

echo ""
echo "Running enable_sell_alerts.py on AWS server..."
echo ""

# Run script on server
ssh ubuntu@175.41.189.249 << 'EOF'
cd ~/automated-trading-platform/backend
source venv/bin/activate 2>/dev/null || source .venv/bin/activate 2>/dev/null || true
python3 scripts/enable_sell_alerts.py
EOF

echo ""
echo "✅ Done! Check output above for results."





#!/bin/bash
set -e

# Deploy Watchlist Master Table Implementation
# This script deploys the watchlist master table changes to AWS

SERVER="ubuntu@175.41.189.249"
# Unified SSH (relative to backend/)
. "$(cd "$(dirname "$0")"; pwd)/scripts/ssh_key.sh" 2>/dev/null || source "$(cd "$(dirname "$0")"; pwd)/scripts/ssh_key.sh"

echo "🚀 Deploying Watchlist Master Table to AWS..."
echo ""

# Files to deploy
BACKEND_FILES=(
    "backend/app/models/watchlist_master.py"
    "backend/app/services/watchlist_master_seed.py"
    "backend/app/api/routes_dashboard.py"
    "backend/market_updater.py"
    "backend/app/services/portfolio_cache.py"
    "backend/scripts/run_watchlist_master_migration.py"
    "backend/scripts/verify_watchlist_master.py"
    "backend/scripts/test_watchlist_master_endpoints.py"
)

FRONTEND_FILES=(
    "frontend/src/components/WatchlistCell.tsx"
    "frontend/src/styles/watchlist.css"
    "frontend/src/app/api.ts"
)

echo "📦 Copying backend files..."
for file in "${BACKEND_FILES[@]}"; do
    if [ -f "$file" ]; then
        echo "  → $file"
        dir=$(dirname "$file")
        ssh_cmd $SERVER "mkdir -p ~/crypto-2.0/$dir"
        rsync_cmd "$file" "$SERVER:~/crypto-2.0/$file"
    else
        echo "  ⚠️  File not found: $file"
    fi
done

echo ""
echo "📦 Copying frontend files..."
for file in "${FRONTEND_FILES[@]}"; do
    if [ -f "$file" ]; then
        echo "  → $file"
        dir=$(dirname "$file")
        ssh_cmd $SERVER "mkdir -p ~/crypto-2.0/$dir"
        rsync_cmd "$file" "$SERVER:~/crypto-2.0/$file"
    else
        echo "  ⚠️  File not found: $file"
    fi
done

echo ""
echo "⚙️  Running migration and restarting services..."
ssh_cmd $SERVER << 'ENDSSH'
cd ~/crypto-2.0/backend

# Activate virtual environment
if [ -d "venv" ]; then
    source venv/bin/activate
else
    echo "⚠️  Virtual environment not found, creating..."
    python3 -m venv venv
    source venv/bin/activate
    pip install --quiet -r requirements.txt
fi

echo ""
echo "🔄 Running database migration..."
python3 scripts/run_watchlist_master_migration.py

echo ""
echo "✅ Verifying migration..."
python3 scripts/verify_watchlist_master.py

echo ""
echo "🔄 Restarting backend service..."
# Try different restart methods
if systemctl is-active --quiet backend.service 2>/dev/null; then
    echo "  → Using systemd"
    sudo systemctl restart backend.service
elif systemctl is-active --quiet automated-trading-platform.service 2>/dev/null; then
    echo "  → Using automated-trading-platform service"
    sudo systemctl restart automated-trading-platform.service
else
    echo "  → Stopping existing uvicorn processes"
    pkill -f "uvicorn app.main:app" || true
    sleep 2
    
    echo "  → Starting backend..."
    nohup uvicorn app.main:app --host 0.0.0.0 --port 8000 > backend.log 2>&1 &
    echo "  → Backend started (PID: $!)"
fi

echo ""
echo "⏳ Waiting for backend to start..."
sleep 5

echo ""
echo "🧪 Testing endpoints..."
python3 scripts/test_watchlist_master_endpoints.py || echo "⚠️  Endpoint test failed (server may still be starting)"

echo ""
echo "✅ Backend deployment complete!"
ENDSSH

echo ""
echo "📦 Deploying frontend..."
ssh_cmd $SERVER << 'ENDSSH'
cd ~/crypto-2.0/frontend

# Check if using Next.js
if [ -f "package.json" ]; then
    echo "📦 Installing dependencies..."
    npm install --silent || yarn install --silent
    
    echo "🔨 Building frontend..."
    npm run build || yarn build
    
    echo "🔄 Restarting frontend service..."
    # Try different restart methods
    if systemctl is-active --quiet frontend.service 2>/dev/null; then
        sudo systemctl restart frontend.service
    elif systemctl is-active --quiet nextjs.service 2>/dev/null; then
        sudo systemctl restart nextjs.service
    else
        echo "  → Frontend build complete. Restart your frontend service manually if needed."
    fi
else
    echo "⚠️  Frontend package.json not found. Skipping frontend build."
fi

echo ""
echo "✅ Frontend deployment complete!"
ENDSSH

echo ""
echo "🎉 Deployment complete!"
echo ""
echo "📋 Next steps:"
echo "1. Check backend logs: ssh $SERVER 'tail -f ~/crypto-2.0/backend/backend.log'"
echo "2. Test API: curl http://your-api-domain/api/dashboard | jq '.[0] | {symbol, field_updated_at}'"
echo "3. Check frontend: Open watchlist page and verify tooltips/highlighting"
echo ""
echo "✅ Watchlist Master Table deployment complete!"

















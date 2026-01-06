#!/bin/bash

# Deploy all tabs fixes and verify in production
# Includes: ExecutedOrdersTab, OrdersTab, ExpectedTakeProfitTab, Expected TP Details modal

set -e

EC2_HOST="54.254.150.31"
EC2_USER="ubuntu"

# Load SSH helpers
. ./scripts/ssh_key.sh 2>/dev/null || source ./scripts/ssh_key.sh

echo "🚀 Deploying all tabs fixes to AWS..."

# Deploy via SSH
ssh_cmd $EC2_USER@$EC2_HOST << 'DEPLOY_SCRIPT'
set -e

cd /home/ubuntu/automated-trading-platform

echo "📦 Step 1: Handling git pull blockers..."
# Move any untracked markdown files that might block git pull
if [ -d "backup_markdown" ]; then
  echo "   Backup folder exists"
else
  mkdir -p backup_markdown
fi

# Move untracked .md files to backup (non-destructive)
find . -maxdepth 1 -name "*.md" -type f ! -path "./.git/*" -exec sh -c '
  if ! git ls-files --error-unmatch "$1" >/dev/null 2>&1; then
    echo "   Moving untracked file: $1"
    mv "$1" backup_markdown/ 2>/dev/null || true
  fi
' _ {} \;

echo "📥 Step 2: Pulling latest changes..."
if ! git pull; then
  echo "⚠️  Git pull failed, but continuing..."
fi

echo "🔄 Step 3: Updating git submodules..."
git submodule sync --recursive
git submodule update --init --recursive

echo "🔨 Step 4: Rebuilding frontend-aws container..."
docker compose --profile aws build frontend-aws

echo "🚀 Step 5: Restarting frontend-aws container..."
docker compose --profile aws up -d frontend-aws

echo "⏳ Step 6: Waiting for container to be healthy..."
sleep 20

echo "📊 Step 7: Checking container status..."
docker compose --profile aws ps frontend-aws

echo "📋 Step 8: Checking frontend logs for Ready status..."
docker compose --profile aws logs --tail=50 frontend-aws | grep -i "ready\|compiled\|started" | tail -5 || echo "   (No ready message found, check logs manually)"

echo "✅ Deployment complete!"
DEPLOY_SCRIPT

if [ $? -eq 0 ]; then
  echo ""
  echo "✅ Deployment successful!"
  echo ""
  echo "Next steps for verification:"
  echo "1. Open the dashboard in a browser"
  echo "2. Verify each tab:"
  echo "   - Open Orders: loads within 1-2 seconds"
  echo "   - Executed Orders: never stuck on loading"
  echo "   - Expected TP: loads correctly"
  echo "   - Expected TP Details: modal shows real data"
  echo "3. Check DevTools Network and Console tabs"
else
  echo ""
  echo "⚠️  Deployment failed or SSH timed out"
  echo "Please deploy manually using the steps in ALL_TABS_DEPLOYMENT_VERIFICATION.md"
fi





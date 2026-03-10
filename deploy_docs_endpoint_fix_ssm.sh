#!/bin/bash
# Deploy fix for /docs/monitoring/watchlist_consistency_report_latest.md 404 error via AWS SSM

set -e

INSTANCE_ID="i-087953603011543c5"
REGION="ap-southeast-1"

echo "🔧 Deploying Docs Endpoint Fix via SSM"
echo "======================================"
echo ""

if ! command -v aws &> /dev/null; then
    echo "❌ AWS CLI not found. Please install it or use manual deployment."
    exit 1
fi

echo "📤 Step 1: Uploading files to server..."
# First, we need to upload the files. Since SSM doesn't support file upload directly,
# we'll create a script that the user can run manually or we'll provide instructions.

echo ""
echo "⚠️  SSM deployment requires manual file upload first."
echo ""
echo "Please run these commands manually on the server (via SSM Session Manager):"
echo ""
echo "1. Copy the updated routes_monitoring.py:"
echo "   (You'll need to upload this file first via S3 or another method)"
echo ""
echo "2. Copy the updated nginx config:"
echo "   (You'll need to upload this file first via S3 or another method)"
echo ""
echo "3. Then run on server:"
echo "   sudo nginx -t"
echo "   sudo systemctl reload nginx"
echo "   sudo systemctl restart trading-backend  # or your backend service name"
echo ""
echo "Alternatively, see deploy_docs_endpoint_fix_manual.sh for step-by-step instructions."






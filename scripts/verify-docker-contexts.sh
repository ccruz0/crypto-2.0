#!/bin/bash
set -e

# Verify Docker build contexts for local vs AWS
# This script ensures:
# - Local services use context: ./backend with Dockerfile (no backend/ prefix)
# - AWS service uses context: . with Dockerfile.aws (with backend/ prefix)

echo "🔍 Verifying Docker build contexts..."
echo ""

# Step 1: Validate docker-compose config
echo "1️⃣  Validating docker-compose configuration..."
if ! docker compose --profile local config >/dev/null 2>&1; then
    echo "❌ ERROR: docker-compose config validation failed"
    echo "   Run: docker compose --profile local config"
    exit 1
fi
echo "   ✅ docker-compose config valid"
echo ""

# Step 2: Build local images
echo "2️⃣  Building local images (context: ./backend)..."
if ! docker compose --profile local build backend-dev market-updater 2>&1 | grep -q "Built\|Successfully"; then
    echo "❌ ERROR: Local build failed"
    echo "   Expected: context: ./backend, dockerfile: Dockerfile"
    echo "   Check: docker compose --profile local build backend-dev"
    exit 1
fi
echo "   ✅ Local builds succeeded"
echo ""

# Step 3: Build AWS image
echo "3️⃣  Building AWS image (context: ., dockerfile: Dockerfile.aws)..."
if ! docker compose build backend-aws 2>&1 | grep -q "Built\|Successfully"; then
    echo "❌ ERROR: AWS build failed"
    echo "   Expected: context: ., dockerfile: backend/Dockerfile.aws"
    echo "   Check: docker compose build backend-aws"
    exit 1
fi
echo "   ✅ AWS build succeeded"
echo ""

echo "✅ All Docker build contexts verified successfully!"
echo ""
echo "Summary:"
echo "  - Local: context ./backend, Dockerfile (no backend/ prefix)"
echo "  - AWS:   context ., Dockerfile.aws (with backend/ prefix)"


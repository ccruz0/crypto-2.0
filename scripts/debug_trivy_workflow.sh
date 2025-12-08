#!/bin/bash
###############################################################################
# debug_trivy_workflow.sh
# -----------------------------------------------------------------------------
# This script simulates the GitHub Actions Trivy security scan workflow
# to reproduce and debug issues locally.
#
# Usage:
#   bash scripts/debug_trivy_workflow.sh
#
# Requirements:
#   - Docker must be running
#   - Trivy CLI installed (or use Docker: docker run aquasec/trivy)
###############################################################################

set -e  # Exit on error

REPO_ROOT="/Users/carloscruz/automated-trading-platform"
cd "$REPO_ROOT" || exit 1

echo "=========================================="
echo "Trivy Workflow Debug Script"
echo "=========================================="
echo ""

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Check if Docker is running
if ! docker info > /dev/null 2>&1; then
    echo -e "${RED}ERROR: Docker is not running${NC}"
    exit 1
fi

# Check if Trivy is available (try CLI first, then Docker)
TRIVY_CMD=""
if command -v trivy &> /dev/null; then
    TRIVY_CMD="trivy"
    echo -e "${GREEN}✓ Using Trivy CLI${NC}"
elif docker run --rm aquasec/trivy version > /dev/null 2>&1; then
    TRIVY_CMD="docker run --rm -v /var/run/docker.sock:/var/run/docker.sock -v $(pwd):/workspace -w /workspace aquasec/trivy"
    echo -e "${YELLOW}⚠ Using Trivy via Docker${NC}"
else
    echo -e "${RED}ERROR: Trivy not found. Install it or ensure Docker can run aquasec/trivy${NC}"
    exit 1
fi

echo ""
echo "=========================================="
echo "Step 1: Building Docker Images"
echo "=========================================="
echo ""

# Build frontend image
echo "Building frontend image..."
if docker build -t local/atp-frontend:ci -f ./frontend/Dockerfile ./frontend 2>&1; then
    echo -e "${GREEN}✓ Frontend image built successfully${NC}"
    FRONTEND_BUILT=true
else
    echo -e "${RED}✗ Frontend image build failed${NC}"
    FRONTEND_BUILT=false
fi

echo ""

# Build backend image
echo "Building backend image..."
if docker build -t local/atp-backend:ci -f ./backend/Dockerfile ./backend 2>&1; then
    echo -e "${GREEN}✓ Backend image built successfully${NC}"
    BACKEND_BUILT=true
else
    echo -e "${RED}✗ Backend image build failed${NC}"
    BACKEND_BUILT=false
fi

echo ""

# Build db image (optional)
if [ -f "./docker/postgres/Dockerfile" ]; then
    echo "Building db image..."
    if docker build -t local/atp-postgres:ci -f ./docker/postgres/Dockerfile ./docker/postgres 2>&1; then
        echo -e "${GREEN}✓ DB image built successfully${NC}"
        DB_BUILT=true
    else
        echo -e "${RED}✗ DB image build failed${NC}"
        DB_BUILT=false
    fi
else
    echo "Skipping DB image (Dockerfile not found)"
    DB_BUILT=false
fi

echo ""
echo "=========================================="
echo "Step 2: Trivy Image Scans"
echo "=========================================="
echo ""

# Scan frontend image
if [ "$FRONTEND_BUILT" = true ]; then
    echo "Scanning frontend image..."
    if $TRIVY_CMD image --severity HIGH,CRITICAL --ignore-unfixed --exit-code 1 --format json --output trivy-frontend.json local/atp-frontend:ci 2>&1; then
        echo -e "${GREEN}✓ Frontend scan completed (no HIGH/CRITICAL vulnerabilities)${NC}"
    else
        SCAN_EXIT=$?
        if [ $SCAN_EXIT -eq 1 ]; then
            echo -e "${RED}✗ Frontend scan found HIGH/CRITICAL vulnerabilities${NC}"
        else
            echo -e "${RED}✗ Frontend scan failed with exit code $SCAN_EXIT${NC}"
        fi
    fi
else
    echo -e "${YELLOW}⚠ Skipping frontend scan (image not built)${NC}"
fi

echo ""

# Scan backend image
if [ "$BACKEND_BUILT" = true ]; then
    echo "Scanning backend image..."
    if $TRIVY_CMD image --severity HIGH,CRITICAL --ignore-unfixed --exit-code 1 --format json --output trivy-backend.json local/atp-backend:ci 2>&1; then
        echo -e "${GREEN}✓ Backend scan completed (no HIGH/CRITICAL vulnerabilities)${NC}"
    else
        SCAN_EXIT=$?
        if [ $SCAN_EXIT -eq 1 ]; then
            echo -e "${RED}✗ Backend scan found HIGH/CRITICAL vulnerabilities${NC}"
        else
            echo -e "${RED}✗ Backend scan failed with exit code $SCAN_EXIT${NC}"
        fi
    fi
else
    echo -e "${YELLOW}⚠ Skipping backend scan (image not built)${NC}"
fi

echo ""

# Scan db image
if [ "$DB_BUILT" = true ]; then
    echo "Scanning db image..."
    if $TRIVY_CMD image --severity HIGH,CRITICAL --ignore-unfixed --exit-code 1 --format json --output trivy-db.json local/atp-postgres:ci 2>&1; then
        echo -e "${GREEN}✓ DB scan completed (no HIGH/CRITICAL vulnerabilities)${NC}"
    else
        SCAN_EXIT=$?
        if [ $SCAN_EXIT -eq 1 ]; then
            echo -e "${RED}✗ DB scan found HIGH/CRITICAL vulnerabilities${NC}"
        else
            echo -e "${RED}✗ DB scan failed with exit code $SCAN_EXIT${NC}"
        fi
    fi
else
    echo -e "${YELLOW}⚠ Skipping DB scan (image not built)${NC}"
fi

echo ""
echo "=========================================="
echo "Step 3: Trivy Filesystem Scan"
echo "=========================================="
echo ""

# Filesystem scan (exit-code 0 to not fail, but still report)
echo "Scanning filesystem..."
if $TRIVY_CMD fs --severity HIGH,CRITICAL --ignore-unfixed --exit-code 0 --format json --output trivy-fs.json . 2>&1; then
    echo -e "${GREEN}✓ Filesystem scan completed${NC}"
else
    echo -e "${YELLOW}⚠ Filesystem scan completed with findings (non-blocking)${NC}"
fi

echo ""
echo "=========================================="
echo "Summary"
echo "=========================================="
echo ""

# Check if any scan reports exist and show summary
if [ -f "trivy-frontend.json" ]; then
    echo "Frontend scan report: trivy-frontend.json"
fi
if [ -f "trivy-backend.json" ]; then
    echo "Backend scan report: trivy-backend.json"
fi
if [ -f "trivy-db.json" ]; then
    echo "DB scan report: trivy-db.json"
fi
if [ -f "trivy-fs.json" ]; then
    echo "Filesystem scan report: trivy-fs.json"
fi

echo ""
echo "=========================================="
echo "Root Cause Analysis"
echo "=========================================="
echo ""

# Common issues to check
echo "Checking for common issues:"
echo ""

# Check if images exist
if [ "$FRONTEND_BUILT" = false ]; then
    echo -e "${RED}✗ Frontend image was not built - Trivy will fail if it tries to scan a non-existent image${NC}"
fi
if [ "$BACKEND_BUILT" = false ]; then
    echo -e "${RED}✗ Backend image was not built - Trivy will fail if it tries to scan a non-existent image${NC}"
fi

# Check if Trivy can access Docker images
if docker images | grep -q "local/atp-frontend.*ci"; then
    echo -e "${GREEN}✓ Frontend image exists in Docker${NC}"
else
    echo -e "${RED}✗ Frontend image not found in Docker${NC}"
fi

if docker images | grep -q "local/atp-backend.*ci"; then
    echo -e "${GREEN}✓ Backend image exists in Docker${NC}"
else
    echo -e "${RED}✗ Backend image not found in Docker${NC}"
fi

echo ""
echo "=========================================="
echo "Debug script completed"
echo "=========================================="
echo ""
echo "If you see errors above, those are likely the same issues causing"
echo "the GitHub Actions workflow to fail. The workflow should:"
echo "  1. Only scan images that were successfully built"
echo "  2. Handle missing images gracefully"
echo "  3. Use a recent version of the Trivy action"
echo ""

#!/bin/bash

# ==========================================
# Local Development Environment Setup
# ==========================================
# This script sets up and starts your local development environment

set -e

echo "========================================="
echo "🚀 Local Development Environment"
echo "========================================="
echo ""

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

print_status() {
    echo -e "${GREEN}[✓]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[!]${NC} $1"
}

print_error() {
    echo -e "${RED}[✗]${NC} $1"
}

# Check if Docker is running
if ! docker info > /dev/null 2>&1; then
    print_error "Docker is not running. Please start Docker Desktop."
    exit 1
fi

print_status "Docker is running"

# Check if .env files exist
if [ ! -f .env ]; then
    print_warning ".env file not found. Creating from template..."
    cat > .env << 'EOF'
POSTGRES_DB=atp
POSTGRES_USER=trader
POSTGRES_PASSWORD=traderpass
ENVIRONMENT=local
LIVE_TRADING=false
EOF
    print_status "Created .env file"
fi

if [ ! -f .env.local ]; then
    print_warning ".env.local file not found. Creating from template..."
    cat > .env.local << 'EOF'
# Local development overrides
ENVIRONMENT=local
NODE_ENV=development
LIVE_TRADING=false
EOF
    print_status "Created .env.local file"
fi

# Set environment variables
export ENVIRONMENT=local
export NODE_ENV=development

# Start services — explicit list only.
# Both `backend` and `backend-dev` are on the `local` profile and bind :8002;
# a bare `docker compose --profile local up` starts both and conflicts on the port.
# Prefer hot-reload backend-dev for day-to-day local work (see DEV.md).
LOCAL_SERVICES=(db backend-dev frontend)
print_status "Starting local stack: ${LOCAL_SERVICES[*]} (profile local)..."
print_warning "Do not run bare 'docker compose --profile local up' — backend + backend-dev both claim :8002."
docker compose --profile local up -d --build "${LOCAL_SERVICES[@]}"

echo ""
print_status "Waiting for services to be healthy..."
sleep 15

# Check service status
print_status "Service Status:"
docker compose --profile local ps

echo ""
echo "========================================="
echo "✅ Local Development Environment Ready!"
echo "========================================="
echo ""
echo "📍 Services:"
echo "   Backend:  http://localhost:8002  (backend-dev, hot reload)"
echo "   Frontend: http://localhost:3000"
echo "   Database: Docker service db (no host port by default)"
echo ""
echo "🔧 Useful Commands:"
echo "   View logs:        docker compose --profile local logs -f backend-dev frontend"
echo "   Stop services:    docker compose --profile local down"
echo "   Restart backend:  docker compose --profile local restart backend-dev"
echo "   Restart frontend: docker compose --profile local restart frontend"
echo ""
echo "📦 To deploy to AWS after testing:"
echo "   ./deploy_to_aws.sh"
echo ""


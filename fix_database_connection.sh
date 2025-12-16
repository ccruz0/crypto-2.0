#!/bin/bash
# Fix database connection issues for AWS deployment

set -e

echo "=========================================="
echo "Database Connection Fix Script"
echo "=========================================="
echo ""

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Check if we're in the right directory
if [ ! -f "docker-compose.yml" ]; then
    echo -e "${RED}Error: docker-compose.yml not found. Please run this script from the project root.${NC}"
    exit 1
fi

echo "🔍 Checking current status..."
echo ""

# Check if Docker is running
if ! docker info > /dev/null 2>&1; then
    echo -e "${RED}Error: Docker is not running. Please start Docker first.${NC}"
    exit 1
fi

# Check database container
DB_CONTAINER=$(docker ps --filter "name=postgres_hardened" --format "{{.Names}}" | head -1)
if [ -z "$DB_CONTAINER" ]; then
    echo -e "${YELLOW}⚠️  Database container is not running${NC}"
    echo "🚀 Starting database container..."
    docker-compose --profile aws up -d db
    echo "⏳ Waiting for database to be ready..."
    sleep 5
    DB_CONTAINER=$(docker ps --filter "name=postgres_hardened" --format "{{.Names}}" | head -1)
    if [ -z "$DB_CONTAINER" ]; then
        echo -e "${RED}Error: Failed to start database container${NC}"
        exit 1
    fi
    echo -e "${GREEN}✅ Database container started: $DB_CONTAINER${NC}"
else
    echo -e "${GREEN}✅ Database container is running: $DB_CONTAINER${NC}"
fi

# Check backend container
BACKEND_CONTAINER=$(docker ps --filter "name=backend-aws" --format "{{.Names}}" | head -1)
if [ -z "$BACKEND_CONTAINER" ]; then
    echo -e "${YELLOW}⚠️  Backend container is not running${NC}"
    echo "🚀 Starting backend container..."
    docker-compose --profile aws up -d backend-aws
    echo "⏳ Waiting for backend to be ready..."
    sleep 10
    BACKEND_CONTAINER=$(docker ps --filter "name=backend-aws" --format "{{.Names}}" | head -1)
    if [ -z "$BACKEND_CONTAINER" ]; then
        echo -e "${RED}Error: Failed to start backend container${NC}"
        exit 1
    fi
    echo -e "${GREEN}✅ Backend container started: $BACKEND_CONTAINER${NC}"
else
    echo -e "${GREEN}✅ Backend container is running: $BACKEND_CONTAINER${NC}"
fi

echo ""
echo "🔍 Testing database connection from backend container..."
echo ""

# Test if backend can resolve 'db' hostname
if docker exec "$BACKEND_CONTAINER" ping -c 1 db > /dev/null 2>&1; then
    echo -e "${GREEN}✅ Backend can reach database hostname 'db'${NC}"
else
    echo -e "${YELLOW}⚠️  Backend cannot reach database hostname 'db'${NC}"
    echo "   This might indicate a Docker network issue"
    echo ""
    echo "🔄 Restarting containers to fix network connectivity..."
    docker-compose --profile aws restart db backend-aws
    echo "⏳ Waiting for containers to be ready..."
    sleep 10
fi

# Test database connection
echo ""
echo "🔍 Testing database connection..."
if docker exec "$BACKEND_CONTAINER" python -c "
import sys
sys.path.insert(0, '/app')
from app.database import test_database_connection
success, message = test_database_connection()
print('SUCCESS' if success else 'FAILED')
print(message)
" 2>&1 | grep -q "SUCCESS"; then
    echo -e "${GREEN}✅ Database connection test passed!${NC}"
    CONNECTION_OK=true
else
    echo -e "${YELLOW}⚠️  Database connection test failed${NC}"
    CONNECTION_OUTPUT=$(docker exec "$BACKEND_CONTAINER" python -c "
import sys
sys.path.insert(0, '/app')
from app.database import test_database_connection
success, message = test_database_connection()
print(message)
" 2>&1)
    echo "   Error: $CONNECTION_OUTPUT"
    CONNECTION_OK=false
fi

echo ""
echo "=========================================="
if [ "$CONNECTION_OK" = true ]; then
    echo -e "${GREEN}✅ Database connection is working!${NC}"
    echo ""
    echo "You can now try updating alerts in the dashboard."
else
    echo -e "${YELLOW}⚠️  Database connection still has issues${NC}"
    echo ""
    echo "Additional troubleshooting steps:"
    echo "1. Check database logs: docker-compose --profile aws logs db | tail -20"
    echo "2. Check backend logs: docker-compose --profile aws logs backend-aws | tail -20"
    echo "3. Verify DATABASE_URL in backend: docker exec $BACKEND_CONTAINER env | grep DATABASE_URL"
    echo "4. Check Docker network: docker network inspect \$(docker inspect $BACKEND_CONTAINER | grep NetworkMode | cut -d'\"' -f4)"
    echo ""
    echo "If the issue persists, try:"
    echo "  docker-compose --profile aws down"
    echo "  docker-compose --profile aws up -d"
fi
echo "=========================================="

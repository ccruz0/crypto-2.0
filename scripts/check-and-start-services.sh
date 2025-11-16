#!/bin/bash
# Script to check if Docker services are running and start them if not
# Usage: ./check-and-start-services.sh

set -e

PROJECT_DIR="/Users/carloscruz/automated-trading-platform"
LOG_FILE="$HOME/Library/Logs/automated-trading-platform/services.log"

# Create log directory if it doesn't exist
mkdir -p "$(dirname "$LOG_FILE")"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" | tee -a "$LOG_FILE"
}

log "🔍 Checking Docker services status..."

# Change to project directory
cd "$PROJECT_DIR" || {
    log "❌ ERROR: Cannot change to project directory: $PROJECT_DIR"
    exit 1
}

# Check if Docker is running
if ! docker info >/dev/null 2>&1; then
    log "⚠️  Docker is not running. Attempting to start Docker Desktop..."
    open -a Docker 2>/dev/null || {
        log "❌ ERROR: Cannot start Docker Desktop. Please start it manually."
        exit 1
    }
    # Wait for Docker to start (up to 60 seconds)
    for i in {1..60}; do
        sleep 1
        if docker info >/dev/null 2>&1; then
            log "✅ Docker Desktop started successfully"
            break
        fi
        if [ $i -eq 60 ]; then
            log "❌ ERROR: Docker Desktop did not start within 60 seconds"
            exit 1
        fi
    done
fi

# Check if services are running
SERVICES_RUNNING=$(docker compose ps --format json 2>/dev/null | jq -r 'select(.State == "running") | .Name' 2>/dev/null | wc -l || echo "0")

if [ "$SERVICES_RUNNING" -lt 3 ]; then
    log "⚠️  Services are not all running ($SERVICES_RUNNING/3). Starting services..."
    
    # Start services
    docker compose up -d --profile local 2>&1 | tee -a "$LOG_FILE"
    
    if [ $? -eq 0 ]; then
        log "✅ Services started successfully"
        
        # Wait a bit for services to initialize
        sleep 5
        
        # Verify services are running
        docker compose ps --format json 2>/dev/null | jq -r 'select(.State == "running") | .Name' | while read service; do
            log "  ✓ $service is running"
        done
    else
        log "❌ ERROR: Failed to start services"
        exit 1
    fi
else
    log "✅ All services are already running ($SERVICES_RUNNING services)"
fi

# Health check
log "🏥 Performing health check..."
sleep 2

# Check frontend
if curl -s -o /dev/null -w "%{http_code}" http://localhost:3000 | grep -q "200\|302"; then
    log "  ✓ Frontend is responding"
else
    log "  ⚠️  Frontend is not responding correctly"
fi

# Check backend
if curl -s -o /dev/null -w "%{http_code}" http://localhost:8000/ | grep -q "200\|404"; then
    log "  ✓ Backend is responding"
else
    log "  ⚠️  Backend is not responding correctly"
fi

log "✅ Health check completed"

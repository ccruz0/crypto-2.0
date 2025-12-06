#!/usr/bin/env bash
set -euo pipefail

# ============================================
# Health Monitor and Auto-Recovery Script
# ============================================
# This script monitors Docker services and automatically recovers from failures
#
# Usage:
#   ./scripts/health_monitor.sh
#   Or run as a systemd service (see health_monitor.service)
#
# What it does:
#   1. Checks health of all Docker services
#   2. Detects unhealthy or stopped services
#   3. Attempts automatic recovery
#   4. Logs all actions for debugging
# ============================================

# Load unified SSH helper (for remote operations like Nginx checks)
. "$(dirname "$0")/ssh_key.sh" 2>/dev/null || source "$(dirname "$0")/ssh_key.sh"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
LOG_FILE="${PROJECT_DIR}/logs/health_monitor.log"
MAX_RESTART_ATTEMPTS=3
CHECK_INTERVAL=60  # Check every 60 seconds

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

# Ensure log directory exists
mkdir -p "$(dirname "$LOG_FILE")"

log() {
    local level=$1
    shift
    local message="$*"
    local timestamp=$(date '+%Y-%m-%d %H:%M:%S')
    # Try to write to log file, but don't fail if we can't
    if touch "$LOG_FILE" 2>/dev/null; then
        echo -e "[$timestamp] [$level] $message" | tee -a "$LOG_FILE"
    else
        # Fallback to stdout only if we can't write to log file
        echo -e "[$timestamp] [$level] $message"
    fi
}

info() {
    log "INFO" "$@"
}

warn() {
    log "WARN" "$@"
}

error() {
    log "ERROR" "$@"
}

# Check if a service is healthy
check_service_health() {
    local service=$1
    cd "$PROJECT_DIR"
    
    # Use docker compose ps format (doesn't require jq)
    local ps_output=$(docker compose --profile aws ps --format "{{.Service}}\t{{.State}}\t{{.Health}}" "$service" 2>/dev/null || echo "")
    
    if [ -z "$ps_output" ]; then
        return 2  # Service not found or not running
    fi
    
    local container_status=$(echo "$ps_output" | awk '{print $2}' | head -1)
    local health_status=$(echo "$ps_output" | awk '{print $3}' | head -1)
    
    # If no health status column, check if container is running
    if [ -z "$health_status" ] || [ "$health_status" = "-" ]; then
        if [ "$container_status" = "running" ]; then
            return 0  # Running (no healthcheck defined)
        else
            return 2  # Not running
        fi
    fi
    
    if [ "$container_status" = "running" ] && [ "$health_status" = "healthy" ]; then
        return 0  # Healthy
    elif [ "$container_status" = "running" ] && [ "$health_status" = "starting" ]; then
        return 4  # Starting - give it time
    elif [ "$container_status" = "running" ] && [ "$health_status" != "healthy" ] && [ "$health_status" != "starting" ]; then
        return 1  # Running but unhealthy
    elif [ "$container_status" != "running" ]; then
        return 2  # Not running
    else
        return 3  # Unknown state
    fi
}

# Restart a service
restart_service() {
    local service=$1
    cd "$PROJECT_DIR"
    
    info "Restarting service: $service"
    docker compose --profile aws restart "$service" || {
        error "Failed to restart $service, trying stop/start..."
        docker compose --profile aws stop "$service" || true
        sleep 2
        docker compose --profile aws start "$service" || {
            error "Failed to start $service"
            return 1
        }
    }
    
    # Wait a bit for service to start
    sleep 5
    
    # Check if it's now healthy
    local attempts=0
    while [ $attempts -lt 10 ]; do
        if check_service_health "$service"; then
            info "Service $service recovered successfully"
            return 0
        fi
        sleep 3
        attempts=$((attempts + 1))
    done
    
    warn "Service $service restarted but may still be unhealthy"
    return 1
}

# Rebuild and restart a service (for build-related issues)
rebuild_service() {
    local service=$1
    cd "$PROJECT_DIR"
    
    warn "Rebuilding service: $service"
    docker compose --profile aws build "$service" || {
        error "Failed to build $service"
        return 1
    }
    
    docker compose --profile aws up -d "$service" || {
        error "Failed to start rebuilt $service"
        return 1
    }
    
    sleep 10
    return 0
}

# Check database connectivity
check_database() {
    cd "$PROJECT_DIR"
    docker compose --profile aws exec -T db pg_isready -U trader >/dev/null 2>&1
}

# Check Nginx status
check_nginx() {
    local server="${SERVER:-175.41.189.249}"
    ssh_cmd "ubuntu@${server}" "sudo systemctl is-active nginx >/dev/null 2>&1" 2>/dev/null || return 1
}

# Restart Nginx if needed
restart_nginx() {
    local server="${SERVER:-175.41.189.249}"
    ssh_cmd "ubuntu@${server}" "sudo systemctl restart nginx" 2>/dev/null || {
        error "Failed to restart Nginx"
        return 1
    }
    info "Nginx restarted"
    return 0
}

# Main monitoring loop
monitor_services() {
    local restart_counts_file="${PROJECT_DIR}/.restart_counts"
    declare -A restart_counts
    
    # Load restart counts
    if [ -f "$restart_counts_file" ]; then
        while IFS='=' read -r service count; do
            restart_counts["$service"]=$count
        done < "$restart_counts_file"
    fi
    
    cd "$PROJECT_DIR"
    
    # Get list of services
    local services=$(docker compose --profile aws config --services 2>/dev/null || echo "")
    
    if [ -z "$services" ]; then
        error "Failed to get list of services"
        return 1
    fi
    
    for service in $services; do
        # Skip gluetun if it's not critical for basic functionality
        if [ "$service" = "gluetun" ]; then
            continue
        fi
        
        check_service_health "$service"
        local health_status=$?
        
        case $health_status in
            0)
                # Healthy - reset restart count
                restart_counts["$service"]=0
                ;;
            4)
                # Starting - give it time, don't restart yet
                info "Service $service is starting, waiting..."
                ;;
            1)
                # Unhealthy but running
                warn "Service $service is unhealthy"
                restart_counts["$service"]=$((${restart_counts["$service"]:-0} + 1))
                
                if [ ${restart_counts["$service"]:-0} -lt $MAX_RESTART_ATTEMPTS ]; then
                    restart_service "$service" || {
                        warn "Service $service restart failed, will try rebuild on next cycle"
                    }
                else
                    warn "Service $service has exceeded max restart attempts, attempting rebuild..."
                    restart_counts["$service"]=0
                    rebuild_service "$service" || {
                        error "Failed to recover $service after rebuild - manual intervention may be required"
                        # Reset counter to try again later
                        restart_counts["$service"]=0
                    }
                fi
                ;;
            2)
                # Not running
                warn "Service $service is not running"
                restart_counts["$service"]=$((${restart_counts["$service"]:-0} + 1))
                
                if [ ${restart_counts["$service"]:-0} -lt $MAX_RESTART_ATTEMPTS ]; then
                    restart_service "$service" || {
                        error "Failed to start $service"
                    }
                else
                    error "Service $service has exceeded max restart attempts"
                fi
                ;;
            *)
                warn "Service $service has unknown state"
                ;;
        esac
    done
    
    # Save restart counts
    > "$restart_counts_file"
    for service in "${!restart_counts[@]}"; do
        echo "$service=${restart_counts[$service]}" >> "$restart_counts_file"
    done
    
    # Check database
    if ! check_database; then
        warn "Database is not ready, attempting to restart db service..."
        restart_service "db"
    fi
    
    # Check Nginx (only if we can SSH and we're not inside a container)
    # Skip Nginx check if we're running inside Docker (health monitor runs on host)
    if [ -f /.dockerenv ]; then
        : # Skip Nginx check if running in container
    elif check_nginx; then
        : # Nginx is running
    else
        warn "Nginx is not running, attempting restart..."
        restart_nginx || true  # Don't fail if SSH is not available
    fi
}

# Main execution
main() {
    info "Health monitor started"
    info "Project directory: $PROJECT_DIR"
    info "Check interval: ${CHECK_INTERVAL}s"
    
    # Ensure we're in the right directory
    cd "$PROJECT_DIR" || {
        error "Failed to change to project directory: $PROJECT_DIR"
        exit 1
    }
    
    while true; do
        monitor_services || {
            error "Error in monitor_services, continuing..."
        }
        sleep $CHECK_INTERVAL
    done
}

# Run if executed directly
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    main "$@"
fi


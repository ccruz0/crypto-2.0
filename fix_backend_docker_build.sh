#!/bin/bash
# Fix Backend Docker Build and Rebuild Script
# This script fixes the Docker build issue where gunicorn is not installed
# and rebuilds the backend image properly

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

# AWS Configuration
INSTANCE_ID="i-08726dc37133b2454"
REGION="ap-southeast-1"
PROJECT_DIR="/home/ubuntu/automated-trading-platform"

print_header() {
    echo -e "\n${CYAN}========================================${NC}"
    echo -e "${CYAN}$1${NC}"
    echo -e "${CYAN}========================================${NC}\n"
}

print_status() {
    echo -e "${GREEN}✅ $1${NC}"
}

print_warning() {
    echo -e "${YELLOW}⚠️  $1${NC}"
}

print_error() {
    echo -e "${RED}❌ $1${NC}"
}

print_info() {
    echo -e "${BLUE}ℹ️  $1${NC}"
}

# Check AWS CLI
if ! command -v aws &> /dev/null; then
    print_error "AWS CLI is not installed"
    exit 1
fi

# Function to run SSM command and get output
# Usage: run_ssm_command "command1" "command2" ... [wait_time]
run_ssm_command() {
    local wait_time="${!#}"  # Last argument
    local num_args=$#
    
    # Check if last arg is a number (wait time)
    if [[ "$wait_time" =~ ^[0-9]+$ ]]; then
        # Last arg is wait time, rest are commands
        local commands=("${@:1:$((num_args-1))}")
    else
        # No wait time specified, use default
        wait_time=30
        local commands=("$@")
    fi
    
    print_info "Executing command via SSM..."
    
    # Build JSON array of commands
    local json_commands="["
    for i in "${!commands[@]}"; do
        if [ $i -gt 0 ]; then
            json_commands+=", "
        fi
        # Escape quotes in command
        cmd=$(echo "${commands[$i]}" | sed 's/"/\\"/g')
        json_commands+="\"$cmd\""
    done
    json_commands+="]"
    
    COMMAND_ID=$(aws ssm send-command \
        --instance-ids "$INSTANCE_ID" \
        --region "$REGION" \
        --document-name "AWS-RunShellScript" \
        --parameters "commands=$json_commands" \
        --query 'Command.CommandId' \
        --output text 2>/dev/null)
    
    if [ -z "$COMMAND_ID" ]; then
        print_error "Failed to send SSM command"
        return 1
    fi
    
    print_info "Command ID: $COMMAND_ID (waiting up to ${wait_time}s for execution...)"
    
    # Wait for command to complete
    for i in $(seq 1 $wait_time); do
        STATUS=$(aws ssm get-command-invocation \
            --instance-id "$INSTANCE_ID" \
            --region "$REGION" \
            --command-id "$COMMAND_ID" \
            --query 'Status' \
            --output text 2>/dev/null || echo "InProgress")
        
        if [ "$STATUS" = "Success" ] || [ "$STATUS" = "Failed" ]; then
            break
        fi
        if [ $((i % 5)) -eq 0 ]; then
            echo -n "."
        fi
        sleep 1
    done
    echo ""
    
    # Get output
    OUTPUT=$(aws ssm get-command-invocation \
        --instance-id "$INSTANCE_ID" \
        --region "$REGION" \
        --command-id "$COMMAND_ID" \
        --query 'StandardOutputContent' \
        --output text 2>/dev/null)
    
    ERROR_OUTPUT=$(aws ssm get-command-invocation \
        --instance-id "$INSTANCE_ID" \
        --region "$REGION" \
        --command-id "$COMMAND_ID" \
        --query 'StandardErrorContent' \
        --output text 2>/dev/null)
    
    if [ "$STATUS" = "Success" ]; then
        echo "$OUTPUT"
        if [ -n "$ERROR_OUTPUT" ] && [ "$ERROR_OUTPUT" != "None" ]; then
            echo "$ERROR_OUTPUT" >&2
        fi
        return 0
    else
        print_error "Command failed with status: $STATUS"
        echo "$ERROR_OUTPUT" >&2
        echo "$OUTPUT" >&2
        return 1
    fi
}

print_header "Backend Docker Build Fix Script"

# Step 1: Verify requirements.txt has gunicorn
print_header "Step 1: Verifying requirements.txt"
print_info "Checking if gunicorn is in requirements.txt..."

run_ssm_command "cd $PROJECT_DIR && grep -E '^gunicorn' backend/requirements.txt || echo 'gunicorn not found in requirements.txt'" 10

# Step 2: Stop and remove old container
print_header "Step 2: Cleaning Up Old Container"
print_info "Stopping and removing old backend container..."

run_ssm_command "cd $PROJECT_DIR && docker compose --profile aws stop backend-aws 2>/dev/null || true" "docker compose --profile aws rm -f backend-aws 2>/dev/null || true" 15

# Step 3: Remove old image to force fresh build
print_header "Step 3: Removing Old Image"
print_info "Removing old backend image to force fresh build..."

run_ssm_command "cd $PROJECT_DIR && (docker rmi automated-trading-platform-backend-aws 2>/dev/null || docker rmi \$(docker images | grep backend-aws | awk '{print \$3}' | head -1) 2>/dev/null || echo 'No old image to remove')" 15

# Step 4: Clean up build cache
print_header "Step 4: Cleaning Build Cache"
print_info "Pruning Docker build cache..."

run_ssm_command "docker builder prune -f" 10

# Step 5: Rebuild image with --no-cache
print_header "Step 5: Rebuilding Backend Image"
print_warning "This will take 3-5 minutes. Please wait..."

# Build with explicit verification that gunicorn gets installed
print_info "Building Docker image (this will take 3-5 minutes)..."
run_ssm_command "cd $PROJECT_DIR" "echo 'Starting Docker build...'" "docker compose --profile aws build --no-cache backend-aws > /tmp/docker_build.log 2>&1" "echo 'Build completed. Last 30 lines of build log:'" "tail -30 /tmp/docker_build.log" 300

# Step 6: Verify gunicorn is in the image
print_header "Step 6: Verifying Gunicorn Installation"
print_info "Checking if gunicorn is installed in the new image..."

# Create a test container to check gunicorn
run_ssm_command "cd $PROJECT_DIR" "IMAGE_ID=\$(docker images | grep backend-aws | head -1 | awk '{print \$3}')" "echo \"Image ID: \$IMAGE_ID\"" "echo 'Testing gunicorn installation in image...'" "docker run --rm \$IMAGE_ID pip list | grep gunicorn || echo 'ERROR: gunicorn not found in image'" 30

# Step 7: Start the container
print_header "Step 7: Starting Backend Container"
print_info "Starting backend container with new image..."

run_ssm_command "cd $PROJECT_DIR" "docker compose --profile aws up -d backend-aws" 15

# Step 8: Wait for container to start
print_header "Step 8: Waiting for Container to Start"
print_info "Waiting 30 seconds for backend to initialize..."

sleep 30

# Step 9: Check container status
print_header "Step 9: Checking Container Status"
run_ssm_command "cd $PROJECT_DIR" "docker compose --profile aws ps backend-aws" 10

# Step 10: Check logs for errors
print_header "Step 10: Checking Container Logs"
print_info "Recent container logs (checking for gunicorn errors)..."

run_ssm_command "cd $PROJECT_DIR" "docker compose --profile aws logs --tail=30 backend-aws 2>&1 | tail -20" 10

# Step 11: Test health endpoint
print_header "Step 11: Testing Health Endpoints"
print_info "Testing /ping_fast endpoint..."

HEALTH_TEST=$(run_ssm_command "curl -s -f --max-time 10 http://localhost:8002/ping_fast && echo ' - OK' || echo ' - FAILED'" 15)

if echo "$HEALTH_TEST" | grep -q "OK"; then
    print_status "Health endpoint is responding!"
else
    print_warning "Health endpoint test: $HEALTH_TEST"
fi

# Step 12: Test monitoring endpoint
print_info "Testing /api/monitoring/summary endpoint..."

MONITORING_TEST=$(run_ssm_command "curl -s --max-time 10 http://localhost:8002/api/monitoring/summary | head -c 200" 15)

if echo "$MONITORING_TEST" | grep -q "backend_health"; then
    print_status "Monitoring endpoint is responding!"
    BACKEND_HEALTH=$(echo "$MONITORING_TEST" | grep -o '"backend_health":"[^"]*"' | cut -d'"' -f4 || echo "unknown")
    print_info "Backend health status: $BACKEND_HEALTH"
else
    print_warning "Monitoring endpoint may still be starting"
fi

# Step 13: Test external access
print_header "Step 12: Testing External Access"
print_info "Testing external dashboard access..."

sleep 5
EXTERNAL_CHECK=$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 "https://dashboard.hilovivo.com/api/monitoring/summary" 2>/dev/null || echo "000")

if [ "$EXTERNAL_CHECK" = "200" ]; then
    print_status "External access is working! (HTTP $EXTERNAL_CHECK)"
elif [ "$EXTERNAL_CHECK" = "503" ]; then
    print_warning "External access shows HTTP 503 (backend may still be starting)"
    print_info "Wait 30-60 seconds and refresh the dashboard"
else
    print_warning "External access shows HTTP $EXTERNAL_CHECK"
fi

# Final summary
print_header "Build Fix Summary"
print_header "Final Summary"

echo "Container Status:"
run_ssm_command "cd $PROJECT_DIR" "docker compose --profile aws ps backend-aws" 10

echo ""
echo "If gunicorn errors persist, check:"
echo "  1. Docker build logs: /tmp/docker_build.log on server"
echo "  2. Container logs: docker compose --profile aws logs backend-aws"
echo "  3. Verify requirements.txt is correct"
echo ""
echo "To manually verify gunicorn installation:"
echo "  docker exec backend-aws-1 pip list | grep gunicorn"

print_status "Script completed!"
print_info "Check the dashboard in 1-2 minutes to verify backend health"


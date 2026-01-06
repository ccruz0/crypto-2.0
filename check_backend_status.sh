#!/bin/bash
# Script to check backend status on AWS server

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
run_ssm_command() {
    local wait_time="${!#}"  # Last argument
    local num_args=$#
    
    # Check if last arg is a number (wait time)
    if [[ "$wait_time" =~ ^[0-9]+$ ]]; then
        local commands=("${@:1:$((num_args-1))}")
    else
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
    
    print_info "Command ID: $COMMAND_ID (waiting up to ${wait_time}s...)"
    
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

print_header "Backend Status Check"

# Step 1: Check container status
print_header "Step 1: Container Status"
print_info "Checking backend-aws container status..."

run_ssm_command "cd $PROJECT_DIR && docker compose --profile aws ps backend-aws" 15

# Step 2: Check container logs (last 30 lines)
print_header "Step 2: Recent Container Logs"
print_info "Last 30 lines of backend logs..."

run_ssm_command "cd $PROJECT_DIR && docker compose --profile aws logs --tail=30 backend-aws 2>&1" 15

# Step 3: Check if gunicorn is running
print_header "Step 3: Gunicorn Process Check"
print_info "Checking if gunicorn process is running..."

run_ssm_command "cd $PROJECT_DIR && docker compose --profile aws exec backend-aws ps aux | grep gunicorn || echo 'No gunicorn process found'" 15

# Step 4: Check if gunicorn is installed
print_header "Step 4: Gunicorn Installation Check"
print_info "Checking if gunicorn is installed..."

run_ssm_command "cd $PROJECT_DIR && docker compose --profile aws exec backend-aws pip list | grep gunicorn || echo 'gunicorn not found in pip list'" 15

# Step 5: Test health endpoint (internal)
print_header "Step 5: Health Endpoint Test (Internal)"
print_info "Testing /ping_fast endpoint from inside container..."

run_ssm_command "cd $PROJECT_DIR && docker compose --profile aws exec backend-aws curl -s -f --max-time 5 http://localhost:8002/ping_fast && echo ' - OK' || echo ' - FAILED'" 15

# Step 6: Test health endpoint (external)
print_header "Step 6: Health Endpoint Test (External)"
print_info "Testing /ping_fast endpoint from host..."

run_ssm_command "curl -s -f --max-time 5 http://localhost:8002/ping_fast && echo ' - OK' || echo ' - FAILED'" 15

# Step 7: Test dashboard state endpoint
print_header "Step 7: Dashboard State Endpoint Test"
print_info "Testing /api/dashboard/state endpoint..."

run_ssm_command "curl -s --max-time 10 http://localhost:8002/api/dashboard/state | head -c 200 || echo 'FAILED to get response'" 15

# Step 8: Check nginx status
print_header "Step 8: Nginx Status"
print_info "Checking nginx container status..."

run_ssm_command "cd $PROJECT_DIR && docker compose --profile aws ps nginx 2>&1 || echo 'Nginx container not found'" 15

# Step 9: Check nginx logs for backend errors
print_header "Step 9: Nginx Logs (Backend Errors)"
print_info "Checking nginx logs for backend connection errors..."

run_ssm_command "cd $PROJECT_DIR && docker compose --profile aws logs --tail=20 nginx 2>&1 | grep -i 'backend\|503\|502\|upstream' || echo 'No backend errors in nginx logs'" 15

# Step 10: Check port 8002
print_header "Step 10: Port 8002 Check"
print_info "Checking if port 8002 is listening..."

run_ssm_command "netstat -tlnp 2>/dev/null | grep :8002 || ss -tlnp 2>/dev/null | grep :8002 || echo 'Port 8002 not found in listening ports'" 15

# Final summary
print_header "Summary"
echo ""
echo "If backend is not running or not responding:"
echo "  1. Check logs: docker compose --profile aws logs backend-aws"
echo "  2. Restart backend: docker compose --profile aws restart backend-aws"
echo "  3. Check if gunicorn is installed: docker exec backend-aws-1 pip list | grep gunicorn"
echo "  4. If gunicorn missing, run: ./fix_backend_docker_build.sh"
echo ""

print_status "Status check completed!"





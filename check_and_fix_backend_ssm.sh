#!/bin/bash
# Backend Health Check and Fix Script using AWS SSM
# This script uses AWS Session Manager to check and fix backend on remote server

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

print_info() { echo -e "${BLUE}[INFO]${NC} $1"; }
print_success() { echo -e "${GREEN}[✓]${NC} $1"; }
print_warning() { echo -e "${YELLOW}[⚠]${NC} $1"; }
print_error() { echo -e "${RED}[✗]${NC} $1"; }

# AWS Configuration
INSTANCE_ID="i-08726dc37133b2454"
REGION="ap-southeast-1"
PROJECT_DIR="automated-trading-platform"
BACKEND_PORT="8002"

echo ""
echo "=========================================="
echo "Backend Health Check (via AWS SSM)"
echo "=========================================="
echo ""

# Check AWS CLI
if ! command -v aws &> /dev/null; then
    print_error "AWS CLI is not installed"
    exit 1
fi

# Function to run command via SSM
run_ssm_command() {
    local command="$1"
    local output_file=$(mktemp)
    
    print_info "Executing: $command"
    
    COMMAND_ID=$(aws ssm send-command \
        --instance-ids "$INSTANCE_ID" \
        --region "$REGION" \
        --document-name "AWS-RunShellScript" \
        --parameters "commands=[$command]" \
        --output-s3-bucket-name "" \
        --query 'Command.CommandId' \
        --output text 2>/dev/null)
    
    if [ -z "$COMMAND_ID" ]; then
        print_error "Failed to send SSM command"
        return 1
    fi
    
    print_info "Command ID: $COMMAND_ID (waiting for execution...)"
    
    # Wait for command to complete (max 30 seconds)
    for i in {1..30}; do
        STATUS=$(aws ssm get-command-invocation \
            --instance-id "$INSTANCE_ID" \
            --region "$REGION" \
            --command-id "$COMMAND_ID" \
            --query 'Status' \
            --output text 2>/dev/null)
        
        if [ "$STATUS" = "Success" ] || [ "$STATUS" = "Failed" ]; then
            break
        fi
        sleep 1
    done
    
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
        if [ -n "$ERROR_OUTPUT" ]; then
            echo "$ERROR_OUTPUT" >&2
        fi
        return 0
    else
        print_error "Command failed with status: $STATUS"
        echo "$ERROR_OUTPUT" >&2
        return 1
    fi
}

# Step 1: Check Docker backend
print_info "Step 1: Checking Docker backend status..."
DOCKER_CHECK=$(run_ssm_command "cd ~/$PROJECT_DIR && docker compose --profile aws ps backend-aws 2>/dev/null | grep -q 'Up' && echo 'running' || echo 'stopped'")

if echo "$DOCKER_CHECK" | grep -q "running"; then
    print_success "Docker backend is running"
    DOCKER_RUNNING=true
    # Get container details
    run_ssm_command "cd ~/$PROJECT_DIR && docker compose --profile aws ps backend-aws" | grep -E "backend-aws|Up|Exit"
else
    print_warning "Docker backend is not running"
    DOCKER_RUNNING=false
fi

echo ""

# Step 2: Check direct process
print_info "Step 2: Checking direct backend process..."
PROCESS_CHECK=$(run_ssm_command "ps aux | grep -E 'uvicorn.*app.main:app.*port.*8002' | grep -v grep | wc -l")

if [ "$PROCESS_CHECK" -gt 0 ]; then
    print_success "Direct backend process is running"
    PROCESS_RUNNING=true
    run_ssm_command "ps aux | grep -E 'uvicorn.*app.main:app.*port.*8002' | grep -v grep"
else
    print_warning "Direct backend process is not running"
    PROCESS_RUNNING=false
fi

echo ""

# Step 3: Check backend health
print_info "Step 3: Testing backend health endpoint..."
HEALTH_CHECK=$(run_ssm_command "curl -s -o /dev/null -w '%{http_code}' --max-time 5 http://localhost:$BACKEND_PORT/health 2>/dev/null || echo '000'")

if [ "$HEALTH_CHECK" = "200" ]; then
    print_success "Backend health check: OK (HTTP $HEALTH_CHECK)"
    HEALTH_OK=true
else
    print_error "Backend health check: FAILED (HTTP $HEALTH_CHECK)"
    HEALTH_OK=false
fi

echo ""

# Step 4: Check monitoring endpoint
print_info "Step 4: Testing monitoring endpoint..."
MONITORING_CHECK=$(run_ssm_command "curl -s -o /dev/null -w '%{http_code}' --max-time 5 http://localhost:$BACKEND_PORT/api/monitoring/summary 2>/dev/null || echo '000'")

if [ "$MONITORING_CHECK" = "200" ]; then
    print_success "Monitoring endpoint: OK (HTTP $MONITORING_CHECK)"
    MONITORING_OK=true
else
    print_error "Monitoring endpoint: FAILED (HTTP $MONITORING_CHECK)"
    MONITORING_OK=false
fi

echo ""
echo "=========================================="
echo "Status Summary"
echo "=========================================="
echo "Docker Backend:     $([ "$DOCKER_RUNNING" = true ] && echo -e "${GREEN}Running${NC}" || echo -e "${RED}Stopped${NC}")"
echo "Direct Process:     $([ "$PROCESS_RUNNING" = true ] && echo -e "${GREEN}Running${NC}" || echo -e "${RED}Stopped${NC}")"
echo "Health Endpoint:    $([ "$HEALTH_OK" = true ] && echo -e "${GREEN}OK${NC}" || echo -e "${RED}FAILED${NC}")"
echo "Monitoring Endpoint: $([ "$MONITORING_OK" = true ] && echo -e "${GREEN}OK${NC}" || echo -e "${RED}FAILED${NC}")"
echo ""

# If not healthy, offer to fix
if [ "$HEALTH_OK" = false ] || [ "$MONITORING_OK" = false ]; then
    print_warning "Backend is not healthy. Would you like to fix it?"
    echo ""
    echo "Options:"
    echo "  1) Start Docker backend (recommended)"
    echo "  2) Restart Docker backend"
    echo "  3) View backend logs"
    echo "  4) Exit"
    echo ""
    read -p "Enter choice [1-4]: " choice
    
    case $choice in
        1)
            print_info "Starting Docker backend..."
            run_ssm_command "cd ~/$PROJECT_DIR && docker compose --profile aws up -d backend-aws && sleep 5 && docker compose --profile aws ps backend-aws"
            print_success "Docker backend start command executed"
            ;;
        2)
            print_info "Restarting Docker backend..."
            run_ssm_command "cd ~/$PROJECT_DIR && docker compose --profile aws restart backend-aws && sleep 5 && docker compose --profile aws ps backend-aws"
            print_success "Docker backend restart command executed"
            ;;
        3)
            print_info "Fetching backend logs..."
            run_ssm_command "cd ~/$PROJECT_DIR && docker compose --profile aws logs --tail=50 backend-aws 2>/dev/null || echo 'No Docker logs available'"
            ;;
        4)
            print_info "Exiting"
            exit 0
            ;;
        *)
            print_error "Invalid choice"
            exit 1
            ;;
    esac
    
    # Re-check after fix
    echo ""
    print_info "Waiting 5 seconds and re-checking..."
    sleep 5
    
    NEW_HEALTH=$(run_ssm_command "curl -s -o /dev/null -w '%{http_code}' --max-time 5 http://localhost:$BACKEND_PORT/health 2>/dev/null || echo '000'")
    
    if [ "$NEW_HEALTH" = "200" ]; then
        print_success "Backend is now healthy! (HTTP $NEW_HEALTH)"
        
        # Test external access
        sleep 2
        EXTERNAL_CHECK=$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 "https://dashboard.hilovivo.com/api/monitoring/summary" 2>/dev/null || echo "000")
        if [ "$EXTERNAL_CHECK" = "200" ]; then
            print_success "External access is now working! (HTTP $EXTERNAL_CHECK)"
        else
            print_warning "Backend is running but external access shows HTTP $EXTERNAL_CHECK"
            print_info "This might be a caching issue. Try refreshing the dashboard."
        fi
    else
        print_error "Backend is still not healthy (HTTP $NEW_HEALTH)"
        print_info "Check the logs above for errors"
    fi
else
    print_success "Backend is healthy and accessible!"
    
    # Test external access
    EXTERNAL_CHECK=$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 "https://dashboard.hilovivo.com/api/monitoring/summary" 2>/dev/null || echo "000")
    if [ "$EXTERNAL_CHECK" = "200" ]; then
        print_success "External access is also working! (HTTP $EXTERNAL_CHECK)"
    else
        print_warning "Backend is healthy but external access shows HTTP $EXTERNAL_CHECK"
        print_info "This might be an nginx configuration issue"
    fi
fi

echo ""
print_info "Script completed"








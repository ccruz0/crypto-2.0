#!/bin/bash
# Script para actualizar todas las monedas en AWS: alert_enabled=False, trade_enabled=False, trade_on_margin=False

set -e

# Configuration
EC2_HOST="54.254.150.31"
EC2_USER="ubuntu"
# Unified SSH
. ./scripts/ssh_key.sh 2>/dev/null || source ./scripts/ssh_key.sh
PROJECT_DIR="automated-trading-platform"

echo "========================================="
echo "Actualizando monedas en AWS"
echo "========================================="
echo ""

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Function to print colored output
print_status() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Check SSH connection
print_status "Testing SSH connection to AWS..."
ssh_cmd "$EC2_USER@$EC2_HOST" "echo 'SSH connection successful'" || {
    print_error "Cannot connect to AWS instance"
    exit 1
}

# Copy the update script to AWS
print_status "Copying update script to AWS..."
scp_cmd update_all_coins_aws.py "$EC2_USER@$EC2_HOST:~/$PROJECT_DIR/"

# Execute the script inside the backend container
print_status "Executing update script in AWS backend container..."
ssh_cmd "$EC2_USER@$EC2_HOST" << 'UPDATE_SCRIPT'
cd ~/automated-trading-platform

# Execute the script inside the backend container
docker compose exec -T backend python3 /app/update_all_coins_aws.py || {
    echo "⚠️ Error executing script in container, trying alternative method..."
    
    # Alternative: Copy script into container and execute
    docker compose cp update_all_coins_aws.py backend:/app/update_all_coins_aws.py
    docker compose exec -T backend python3 /app/update_all_coins_aws.py
}

echo ""
echo "✅ Update script completed"
UPDATE_SCRIPT

print_status "✅ Update completed successfully!"
echo ""
echo "All coins in AWS should now have:"
echo "  • alert_enabled = False"
echo "  • trade_enabled = False"
echo "  • trade_on_margin = False"


#!/bin/bash
# Test SSH connection to AWS EC2 instances

set -e

# Colors
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m'

# Load SSH configuration
. ./scripts/ssh_key.sh 2>/dev/null || source ./scripts/ssh_key.sh

EC2_HOST_PRIMARY="54.254.150.31"
EC2_HOST_ALTERNATIVE="175.41.189.249"
EC2_USER="ubuntu"

echo "========================================="
echo "Testing SSH Connection to AWS"
echo "========================================="
echo ""
echo "SSH Key: ${SSH_KEY:-$HOME/.ssh/id_rsa}"
echo ""

# Test primary host
echo -e "${YELLOW}Testing primary host: $EC2_HOST_PRIMARY${NC}"
if ssh -o ConnectTimeout=5 -o StrictHostKeyChecking=no "${SSH_OPTS[@]}" "$EC2_USER@$EC2_HOST_PRIMARY" "echo '✅ Connected'" 2>/dev/null; then
    echo -e "${GREEN}✅ Primary host ($EC2_HOST_PRIMARY) is accessible${NC}"
    echo ""
    echo "Testing full connection..."
    ssh_cmd "$EC2_USER@$EC2_HOST_PRIMARY" "echo '✅ SSH working' && uname -a && whoami"
    echo ""
    echo -e "${GREEN}✅ SSH connection to primary host is working!${NC}"
    exit 0
else
    echo -e "${RED}❌ Primary host ($EC2_HOST_PRIMARY) not accessible${NC}"
fi

echo ""

# Test alternative host
echo -e "${YELLOW}Testing alternative host: $EC2_HOST_ALTERNATIVE${NC}"
if ssh -o ConnectTimeout=5 -o StrictHostKeyChecking=no "${SSH_OPTS[@]}" "$EC2_USER@$EC2_HOST_ALTERNATIVE" "echo '✅ Connected'" 2>/dev/null; then
    echo -e "${GREEN}✅ Alternative host ($EC2_HOST_ALTERNATIVE) is accessible${NC}"
    echo ""
    echo "Testing full connection..."
    ssh_cmd "$EC2_USER@$EC2_HOST_ALTERNATIVE" "echo '✅ SSH working' && uname -a && whoami"
    echo ""
    echo -e "${GREEN}✅ SSH connection to alternative host is working!${NC}"
    exit 0
else
    echo -e "${RED}❌ Alternative host ($EC2_HOST_ALTERNATIVE) not accessible${NC}"
fi

echo ""
echo -e "${RED}❌ Cannot connect to either AWS host${NC}"
echo ""
echo "Troubleshooting steps:"
echo "1. Verify SSH key permissions:"
echo "   chmod 600 ~/.ssh/id_rsa"
echo ""
echo "2. Test SSH key manually:"
echo "   ssh -i ~/.ssh/id_rsa ubuntu@54.254.150.31"
echo ""
echo "3. Check AWS Security Group:"
echo "   - Port 22 (SSH) should be open"
echo "   - Source should allow your IP or 0.0.0.0/0"
echo ""
echo "4. Verify instance is running:"
echo "   - Check AWS Console EC2 dashboard"
echo "   - Instance status should be 'running'"
echo ""
echo "5. If using a different key file:"
echo "   export SSH_KEY=/path/to/your/key.pem"
echo "   ./test_aws_ssh.sh"
echo ""
exit 1

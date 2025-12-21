#!/bin/bash
# Setup AWS Elastic IP for Crypto.com API (skip NordVPN dedicated IP)

set -e

echo "🔧 AWS Elastic IP Setup for Crypto.com API"
echo "=========================================="
echo ""

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# Check if AWS CLI is installed
if ! command -v aws &> /dev/null; then
    echo -e "${RED}❌ AWS CLI is not installed${NC}"
    echo "Install it with: pip install awscli or brew install awscli"
    exit 1
fi

# Check AWS credentials
if ! aws sts get-caller-identity &> /dev/null; then
    echo -e "${RED}❌ AWS credentials not configured${NC}"
    echo "Run: aws configure"
    exit 1
fi

echo -e "${GREEN}✅ AWS CLI configured${NC}"
echo ""

# Step 1: Get current instance ID (if running on EC2)
echo "Step 1: Getting EC2 instance information..."
INSTANCE_ID=$(curl -s http://169.254.169.254/latest/meta-data/instance-id 2>/dev/null || echo "")

if [ -z "$INSTANCE_ID" ]; then
    echo -e "${YELLOW}⚠️  Not running on EC2, or metadata service unavailable${NC}"
    echo "Please provide your EC2 instance ID:"
    read -r INSTANCE_ID
else
    echo -e "${GREEN}✅ Found instance ID: $INSTANCE_ID${NC}"
fi

# Step 2: Check if instance already has Elastic IP
echo ""
echo "Step 2: Checking for existing Elastic IP..."
CURRENT_IP=$(aws ec2 describe-instances \
    --instance-ids "$INSTANCE_ID" \
    --query 'Reservations[0].Instances[0].PublicIpAddress' \
    --output text 2>/dev/null || echo "")

if [ -z "$CURRENT_IP" ] || [ "$CURRENT_IP" == "None" ]; then
    echo -e "${YELLOW}⚠️  No public IP found${NC}"
else
    echo -e "${GREEN}✅ Current public IP: $CURRENT_IP${NC}"
    
    # Check if it's an Elastic IP
    ELASTIC_IP_INFO=$(aws ec2 describe-addresses \
        --filters "Name=instance-id,Values=$INSTANCE_ID" \
        --query 'Addresses[0]' \
        --output json 2>/dev/null || echo "{}")
    
    if [ "$ELASTIC_IP_INFO" != "{}" ] && [ "$ELASTIC_IP_INFO" != "null" ]; then
        ELASTIC_IP=$(echo "$ELASTIC_IP_INFO" | grep -o '"PublicIp": "[^"]*"' | cut -d'"' -f4)
        echo -e "${GREEN}✅ Instance already has Elastic IP: $ELASTIC_IP${NC}"
        echo ""
        echo "Your Elastic IP is: $ELASTIC_IP"
        echo "Add this IP to Crypto.com whitelist: https://exchange.crypto.com/"
        exit 0
    fi
fi

# Step 3: Allocate new Elastic IP
echo ""
echo "Step 3: Allocating new Elastic IP..."
ALLOCATION_ID=$(aws ec2 allocate-address \
    --domain vpc \
    --query 'AllocationId' \
    --output text)

if [ -z "$ALLOCATION_ID" ]; then
    echo -e "${RED}❌ Failed to allocate Elastic IP${NC}"
    exit 1
fi

echo -e "${GREEN}✅ Elastic IP allocated: $ALLOCATION_ID${NC}"

# Step 4: Get the Elastic IP address
ELASTIC_IP=$(aws ec2 describe-addresses \
    --allocation-ids "$ALLOCATION_ID" \
    --query 'Addresses[0].PublicIp' \
    --output text)

echo -e "${GREEN}✅ Elastic IP address: $ELASTIC_IP${NC}"

# Step 5: Associate Elastic IP to instance
echo ""
echo "Step 4: Associating Elastic IP to instance..."
aws ec2 associate-address \
    --instance-id "$INSTANCE_ID" \
    --allocation-id "$ALLOCATION_ID" > /dev/null

if [ $? -eq 0 ]; then
    echo -e "${GREEN}✅ Elastic IP associated successfully${NC}"
else
    echo -e "${RED}❌ Failed to associate Elastic IP${NC}"
    echo "You may need to release the Elastic IP manually:"
    echo "aws ec2 release-address --allocation-id $ALLOCATION_ID"
    exit 1
fi

# Step 6: Verify
echo ""
echo "Step 5: Verifying setup..."
sleep 5
VERIFIED_IP=$(aws ec2 describe-instances \
    --instance-ids "$INSTANCE_ID" \
    --query 'Reservations[0].Instances[0].PublicIpAddress' \
    --output text)

if [ "$VERIFIED_IP" == "$ELASTIC_IP" ]; then
    echo -e "${GREEN}✅ Verification successful${NC}"
else
    echo -e "${YELLOW}⚠️  IP may take a few moments to update${NC}"
    echo "Expected: $ELASTIC_IP"
    echo "Current: $VERIFIED_IP"
fi

# Summary
echo ""
echo "=========================================="
echo -e "${GREEN}✅ Setup Complete!${NC}"
echo "=========================================="
echo ""
echo "Your Elastic IP: $ELASTIC_IP"
echo ""
echo "Next steps:"
echo "1. Add this IP to Crypto.com whitelist:"
echo "   https://exchange.crypto.com/ → Settings → API Keys"
echo ""
echo "2. Update .env.aws to disable proxy:"
echo "   USE_CRYPTO_PROXY=false"
echo ""
echo "3. Restart backend:"
echo "   docker compose --profile aws restart backend-aws"
echo ""
echo "4. Test connection:"
echo "   docker compose --profile aws exec backend-aws python scripts/test_crypto_connection.py"
echo ""


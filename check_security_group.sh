#!/bin/bash
# Script to check and update Security Group rules for safe external access
# Requires: AWS CLI configured with appropriate permissions

set -e

INSTANCE_ID="${1:-i-08726dc37133b2454}"  # Default from deploy workflow
MY_IP="${2:-$(curl -s https://api.ipify.org)}"  # Auto-detect if not provided

echo "========================================="
echo "Security Group Configuration Check"
echo "========================================="
echo ""

echo "Your Public IP: $MY_IP"
echo "EC2 Instance ID: $INSTANCE_ID"
echo ""

# Get Security Group ID from instance
echo "1. Getting Security Group from instance..."
SG_ID=$(aws ec2 describe-instances \
  --instance-ids "$INSTANCE_ID" \
  --region ap-southeast-1 \
  --query 'Reservations[0].Instances[0].SecurityGroups[0].GroupId' \
  --output text 2>/dev/null || echo "ERROR")

if [ "$SG_ID" = "ERROR" ] || [ -z "$SG_ID" ]; then
    echo "   ❌ Failed to get Security Group ID"
    echo "   Please check:"
    echo "   - AWS CLI is configured"
    echo "   - Instance ID is correct: $INSTANCE_ID"
    echo "   - You have EC2 read permissions"
    exit 1
fi

echo "   Security Group ID: $SG_ID"
echo ""

# Get current inbound rules
echo "2. Current Inbound Rules:"
aws ec2 describe-security-groups \
  --group-ids "$SG_ID" \
  --region ap-southeast-1 \
  --query 'SecurityGroups[0].IpPermissions[*].[IpProtocol,FromPort,ToPort,IpRanges[*].CidrIp]' \
  --output table 2>/dev/null || echo "   ❌ Failed to get rules"
echo ""

# Check if ports 8002 and 3000 are open
echo "3. Checking ports 8002 and 3000:"
PORT_8002=$(aws ec2 describe-security-groups \
  --group-ids "$SG_ID" \
  --region ap-southeast-1 \
  --query "SecurityGroups[0].IpPermissions[?FromPort==\`8002\` && ToPort==\`8002\`]" \
  --output json 2>/dev/null | jq -r 'length')

PORT_3000=$(aws ec2 describe-security-groups \
  --group-ids "$SG_ID" \
  --region ap-southeast-1 \
  --query "SecurityGroups[0].IpPermissions[?FromPort==\`3000\` && ToPort==\`3000\`]" \
  --output json 2>/dev/null | jq -r 'length')

if [ "$PORT_8002" = "0" ]; then
    echo "   ⚠️  Port 8002 (backend) is NOT open"
else
    echo "   ✅ Port 8002 (backend) has rules"
fi

if [ "$PORT_3000" = "0" ]; then
    echo "   ⚠️  Port 3000 (frontend) is NOT open"
else
    echo "   ✅ Port 3000 (frontend) has rules"
fi
echo ""

echo "4. Recommended Security Group Rules:"
echo "   Inbound Rules to ADD (if not present):"
echo "   - Type: Custom TCP"
echo "     Port: 8002"
echo "     Source: $MY_IP/32"
echo "     Description: Backend API access from my IP only"
echo ""
echo "   - Type: Custom TCP"
echo "     Port: 3000"
echo "     Source: $MY_IP/32"
echo "     Description: Frontend access from my IP only"
echo ""

echo "5. To add these rules, run:"
echo "   aws ec2 authorize-security-group-ingress \\"
echo "     --group-id $SG_ID \\"
echo "     --protocol tcp \\"
echo "     --port 8002 \\"
echo "     --cidr $MY_IP/32 \\"
echo "     --region ap-southeast-1"
echo ""
echo "   aws ec2 authorize-security-group-ingress \\"
echo "     --group-id $SG_ID \\"
echo "     --protocol tcp \\"
echo "     --port 3000 \\"
echo "     --cidr $MY_IP/32 \\"
echo "     --region ap-southeast-1"
echo ""

echo "========================================="
echo "Security Group ID: $SG_ID"
echo "Your IP: $MY_IP"
echo "========================================="




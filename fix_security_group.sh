#!/bin/bash
# Script to safely add Security Group rules for external access
# Usage: ./fix_security_group.sh [INSTANCE_ID] [MY_IP]

set -e

INSTANCE_ID="${1:-i-08726dc37133b2454}"
MY_IP="${2:-$(curl -s https://api.ipify.org)}"
REGION="ap-southeast-1"

echo "========================================="
echo "Security Group Access Fix"
echo "========================================="
echo ""
echo "Instance ID: $INSTANCE_ID"
echo "Your Public IP: $MY_IP"
echo "Region: $REGION"
echo ""

# Get Security Group ID
echo "1. Getting Security Group ID..."
SG_ID=$(aws ec2 describe-instances \
  --instance-ids "$INSTANCE_ID" \
  --region "$REGION" \
  --query 'Reservations[0].Instances[0].SecurityGroups[0].GroupId' \
  --output text 2>/dev/null)

if [ -z "$SG_ID" ] || [ "$SG_ID" = "None" ]; then
    echo "   ❌ Failed to get Security Group ID"
    echo "   Please check:"
    echo "   - AWS CLI is configured: aws configure"
    echo "   - Instance ID is correct: $INSTANCE_ID"
    echo "   - You have EC2 read permissions"
    exit 1
fi

echo "   Security Group ID: $SG_ID"
echo ""

# Check current rules for ports 8002 and 3000
echo "2. Checking current rules..."
PORT_8002_EXISTS=$(aws ec2 describe-security-groups \
  --group-ids "$SG_ID" \
  --region "$REGION" \
  --query "SecurityGroups[0].IpPermissions[?FromPort==\`8002\` && ToPort==\`8002\` && IpProtocol==\`tcp\`]" \
  --output json 2>/dev/null | jq -r 'length')

PORT_3000_EXISTS=$(aws ec2 describe-security-groups \
  --group-ids "$SG_ID" \
  --region "$REGION" \
  --query "SecurityGroups[0].IpPermissions[?FromPort==\`3000\` && ToPort==\`3000\` && IpProtocol==\`tcp\`]" \
  --output json 2>/dev/null | jq -r 'length')

# Check if rule for MY_IP already exists
MY_IP_RULE_8002=$(aws ec2 describe-security-groups \
  --group-ids "$SG_ID" \
  --region "$REGION" \
  --query "SecurityGroups[0].IpPermissions[?FromPort==\`8002\` && ToPort==\`8002\` && IpProtocol==\`tcp\` && IpRanges[?CidrIp==\`$MY_IP/32\`]]" \
  --output json 2>/dev/null | jq -r 'length')

MY_IP_RULE_3000=$(aws ec2 describe-security-groups \
  --group-ids "$SG_ID" \
  --region "$REGION" \
  --query "SecurityGroups[0].IpPermissions[?FromPort==\`3000\` && ToPort==\`3000\` && IpProtocol==\`tcp\` && IpRanges[?CidrIp==\`$MY_IP/32\`]]" \
  --output json 2>/dev/null | jq -r 'length')

echo "   Port 8002 rules exist: $PORT_8002_EXISTS"
echo "   Port 3000 rules exist: $PORT_3000_EXISTS"
echo "   Your IP ($MY_IP/32) already allowed on 8002: $([ "$MY_IP_RULE_8002" -gt 0 ] && echo "YES" || echo "NO")"
echo "   Your IP ($MY_IP/32) already allowed on 3000: $([ "$MY_IP_RULE_3000" -gt 0 ] && echo "YES" || echo "NO")"
echo ""

# Add rules if needed
echo "3. Adding Security Group rules (if needed)..."
echo ""

if [ "$MY_IP_RULE_8002" -eq 0 ]; then
    echo "   Adding rule for port 8002 from $MY_IP/32..."
    aws ec2 authorize-security-group-ingress \
      --group-id "$SG_ID" \
      --protocol tcp \
      --port 8002 \
      --cidr "$MY_IP/32" \
      --region "$REGION" \
      --description "Backend API access from my IP only" 2>&1 | grep -E "(Ingress|error|Error)" || echo "   ✅ Rule added successfully"
else
    echo "   ✅ Port 8002 already allows $MY_IP/32"
fi

if [ "$MY_IP_RULE_3000" -eq 0 ]; then
    echo "   Adding rule for port 3000 from $MY_IP/32..."
    aws ec2 authorize-security-group-ingress \
      --group-id "$SG_ID" \
      --protocol tcp \
      --port 3000 \
      --cidr "$MY_IP/32" \
      --region "$REGION" \
      --description "Frontend access from my IP only" 2>&1 | grep -E "(Ingress|error|Error)" || echo "   ✅ Rule added successfully"
else
    echo "   ✅ Port 3000 already allows $MY_IP/32"
fi

echo ""
echo "4. Verifying rules..."
aws ec2 describe-security-groups \
  --group-ids "$SG_ID" \
  --region "$REGION" \
  --query 'SecurityGroups[0].IpPermissions[?FromPort==`8002` || FromPort==`3000`].[IpProtocol,FromPort,ToPort,IpRanges[*].CidrIp]' \
  --output table 2>/dev/null || echo "   ⚠️  Could not verify rules"

echo ""
echo "========================================="
echo "✅ Security Group rules updated!"
echo "========================================="
echo ""
echo "You can now test external access:"
echo "  curl -m 5 -v http://<EC2_PUBLIC_IP>:8002/api/health"
echo ""
echo "To get EC2 public IP, run on EC2:"
echo "  curl -s http://169.254.169.254/latest/meta-data/public-ipv4"
echo ""



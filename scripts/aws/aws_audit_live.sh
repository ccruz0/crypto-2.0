#!/usr/bin/env bash
# Run live AWS audit commands (read-only). Region: ap-southeast-1.
# Requires: AWS CLI, credentials with ec2:Describe*, ssm:Describe*.
# See: docs/audit/AWS_STATE_AUDIT.md

set -e
REGION="${AWS_REGION:-ap-southeast-1}"

echo "=== AWS Live Audit ($REGION) ==="
echo ""

echo "--- 1) Running instances ---"
aws ec2 describe-instances --region "$REGION" \
  --filters Name=instance-state-name,Values=running \
  --query 'Reservations[*].Instances[*].[InstanceId,Tags[?Key==`Name`].Value|[0],InstanceType,PrivateIpAddress,PublicIpAddress]' \
  --output table

echo ""
echo "--- 2) Instance details (IAM, SGs) ---"
aws ec2 describe-instances --region "$REGION" \
  --filters Name=instance-state-name,Values=running \
  --query 'Reservations[*].Instances[*].{Id:InstanceId,Name:Tags[?Key==`Name`]|[0].Value,IamProfile:IamInstanceProfile.Arn,SecurityGroups:SecurityGroups[*].GroupId}' \
  --output json 2>/dev/null || true

echo ""
echo "--- 3) SSM agent status (all managed instances) ---"
aws ssm describe-instance-information --region "$REGION" \
  --query 'InstanceInformationList[*].{InstanceId:InstanceId,PingStatus:PingStatus}' \
  --output table 2>/dev/null || echo "(no instances or no permission)"

echo ""
echo "--- 4) Known instance IDs SSM status ---"
for id in i-087953603011543c5 i-0d82c172235770a0d i-08726dc37133b2454; do
  status=$(aws ssm describe-instance-information --region "$REGION" \
    --filters "Key=InstanceIds,Values=$id" \
    --query 'InstanceInformationList[0].PingStatus' --output text 2>/dev/null || echo "N/A")
  echo "  $id: $status"
done

echo ""
echo "=== Done. Update docs/audit/AWS_STATE_AUDIT.md with any changes. ==="

#!/usr/bin/env bash
# Create CloudWatch alarm for PROD EC2 instance that triggers automatic recovery
# when StatusCheckFailed_Instance is >= 1 for 2 consecutive 60-second periods.
#
# Usage: ./setup_auto_recovery.sh
# Requires: AWS CLI, credentials with cloudwatch:PutMetricAlarm and cloudwatch:DescribeAlarms
#
# Instance: i-087953603011543c5 (atp-rebuild-2026)
# Region:   ap-southeast-1

set -euo pipefail

INSTANCE_ID="${ATP_PROD_INSTANCE_ID:-i-087953603011543c5}"
REGION="${AWS_REGION:-ap-southeast-1}"
ALARM_NAME="atp-prod-ec2-recover-${INSTANCE_ID}"

RECOVER_ACTION="arn:aws:automate:${REGION}:ec2:recover"

echo "=== EC2 Auto-Recovery Alarm for PROD ==="
echo "Instance: $INSTANCE_ID"
echo "Region:   $REGION"
echo "Alarm:    $ALARM_NAME"
echo ""

echo "Creating CloudWatch alarm..."
aws cloudwatch put-metric-alarm \
  --region "$REGION" \
  --alarm-name "$ALARM_NAME" \
  --alarm-description "Recover PROD EC2 when instance status check fails (see docs/PROD_INCIDENT_2026-03-11_RECOVERY.md)" \
  --metric-name StatusCheckFailed_Instance \
  --namespace AWS/EC2 \
  --statistic Maximum \
  --period 60 \
  --evaluation-periods 2 \
  --threshold 1 \
  --comparison-operator GreaterThanOrEqualToThreshold \
  --dimensions Name=InstanceId,Value="$INSTANCE_ID" \
  --alarm-actions "$RECOVER_ACTION" \
  --treat-missing-data missing

echo ""
echo "Verifying alarm exists..."
ALARM_ARN=$(aws cloudwatch describe-alarms \
  --region "$REGION" \
  --alarm-names "$ALARM_NAME" \
  --query 'MetricAlarms[0].AlarmArn' \
  --output text 2>/dev/null || echo "")

if [ -z "$ALARM_ARN" ] || [ "$ALARM_ARN" = "None" ]; then
  echo "WARNING: Could not retrieve alarm ARN; check Console (CloudWatch → Alarms)."
else
  echo "Alarm ARN: $ALARM_ARN"
fi

STATE=$(aws cloudwatch describe-alarms \
  --region "$REGION" \
  --alarm-names "$ALARM_NAME" \
  --query 'MetricAlarms[0].StateValue' \
  --output text 2>/dev/null || echo "UNKNOWN")
echo "State:    ${STATE:-UNKNOWN}"
echo ""
echo "=== Done ==="
echo "Recovery action will run when StatusCheckFailed_Instance >= 1 for 2 x 60s."
echo "No ATP scripts, docker, nginx, or timers were modified."

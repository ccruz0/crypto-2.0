#!/usr/bin/env bash
# Retired: do not attach Bedrock to IAM user jarvis-lab-bedrock.
# LAB must use the EC2 instance role (create_atp_lab_ec2_role.sh).
echo "FAIL: attach_jarvis_lab_bedrock_iam_policy.sh is retired." >&2
echo "Use AWS_PROFILE=carlos-sso ./scripts/aws/create_atp_lab_ec2_role.sh" >&2
echo "then AWS_PROFILE=carlos-sso ./scripts/aws/switch_lab_to_instance_role.sh" >&2
echo "Do not create new access keys for jarvis-lab-bedrock." >&2
exit 1

#!/usr/bin/env bash
# RETIRED. Static AWS keys must not be stored in SSM.
# Production uses instance role atp-backend-ec2-role (see scripts/aws/create_atp_backend_ec2_role.sh).
echo "FAIL: store_aws_creds_for_atp_ssm.sh is retired. Do not put AWS_ACCESS_KEY_ID in SSM." >&2
echo "Use the EC2 instance role atp-backend-ec2-role instead." >&2
exit 1

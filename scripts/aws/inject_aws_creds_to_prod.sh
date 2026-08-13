#!/usr/bin/env bash
# RETIRED. Static AWS keys must not be injected into prod runtime.env.
# Production uses instance role atp-backend-ec2-role.
# Cutover: scripts/aws/switch_prod_to_instance_role.sh
echo "FAIL: inject_aws_creds_to_prod.sh is retired. Do not inject AWS_ACCESS_KEY_ID into runtime.env." >&2
echo "Use AWS_PROFILE=carlos-sso ./scripts/aws/switch_prod_to_instance_role.sh" >&2
exit 1

#!/usr/bin/env bash
# Retired: GitHub Actions must use OIDC (AWS_DEPLOY_ROLE_ARN), not static keys.
echo "FAIL: set_aws_github_secrets.sh is retired." >&2
echo "Do not put AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY in GitHub Actions secrets." >&2
echo "Use secret AWS_DEPLOY_ROLE_ARN=arn:aws:iam::634531197711:role/gha-deploy-frontend" >&2
echo "Apply role policy: AWS_PROFILE=carlos-sso ./scripts/aws/put_gha_deploy_role_policy.sh" >&2
exit 1

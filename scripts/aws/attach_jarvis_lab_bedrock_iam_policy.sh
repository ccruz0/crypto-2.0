#!/usr/bin/env bash
# Attach Bedrock invoke permissions to the LAB-scoped IAM user jarvis-lab-bedrock.
#
# Requires admin IAM credentials (NOT the EC2_SSM_Role on atp-rebuild-2026).
# Run from an operator workstation or CloudShell with iam:PutUserPolicy.
#
# After attach, verify from backend-lab (read-only):
#   docker exec automated-trading-platform-backend-lab python3 -c "
#     import boto3; print(boto3.client('sts').get_caller_identity()['Arn'])"
#   # then minimal invoke — see docs/runbooks/LAB_JARVIS_BUILDER_BOOTSTRAP.md
#
# See: docs/runbooks/LAB_JARVIS_BUILDER_BOOTSTRAP.md § Phase 1d
set -euo pipefail

IAM_USER="${JARVIS_LAB_BEDROCK_IAM_USER:-jarvis-lab-bedrock}"
POLICY_NAME="${JARVIS_LAB_BEDROCK_POLICY_NAME:-jarvis-lab-bedrock-invoke}"

POLICY_DOC="$(cat <<'EOF'
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "JarvisLabBedrockInvoke",
      "Effect": "Allow",
      "Action": [
        "bedrock:InvokeModel",
        "bedrock:InvokeModelWithResponseStream"
      ],
      "Resource": "*"
    }
  ]
}
EOF
)"

echo "=== Attach Bedrock invoke policy to IAM user: ${IAM_USER} ==="
echo "Policy name: ${POLICY_NAME}"
echo ""

if ! ID=$(aws sts get-caller-identity --output json 2>/dev/null); then
  echo "FAIL: no AWS credentials. Configure admin IAM and retry." >&2
  exit 1
fi
echo "Caller: $(echo "$ID" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['Arn'])")"
echo ""

aws iam put-user-policy \
  --user-name "$IAM_USER" \
  --policy-name "$POLICY_NAME" \
  --policy-document "$POLICY_DOC"

echo ""
echo "PASS: inline policy ${POLICY_NAME} attached to ${IAM_USER}"
echo ""
echo "Verify (from LAB backend container on host with creds in runtime.env.lab):"
echo "  docker exec automated-trading-platform-backend-lab python3 -c \\"
echo "    \"import json,boto3; r=boto3.client('bedrock-runtime',region_name='ap-southeast-1'); \\"
echo "     body=json.dumps({'anthropic_version':'bedrock-2023-05-31','max_tokens':16, \\"
echo "       'messages':[{'role':'user','content':[{'type':'text','text':'Reply: bedrock-ok'}]}]}); \\"
echo "     p=json.loads(r.invoke_model(modelId='anthropic.claude-3-5-sonnet-20241022-v2:0', \\"
echo "       contentType='application/json',accept='application/json',body=body)['body'].read()); \\"
echo "     print('invoke_ok', ''.join(b.get('text','') for b in p.get('content',[])))\""
echo ""
echo "If invoke fails with ResourceNotFoundException, enable model access in Bedrock console"
echo "for ap-southeast-1 or set JARVIS_BEDROCK_REGION / JARVIS_BEDROCK_MODEL_ID in runtime.env.lab."

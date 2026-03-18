#!/usr/bin/env bash
# One-shot SSM: fetch Notion secret from SSM on LAB, update .env.aws, render, restart, verify, pickup.
# Run from your machine (AWS CLI). LAB instance role must have ssm:GetParameter for
#   /automated-trading-platform/lab/notion/api_key
# If the parameter is missing, create it first: ./scripts/aws/store_lab_notion_api_key_ssm.sh
#
# Usage: ./scripts/aws/lab_notion_oneliner_ssm.sh
#        LAB_INSTANCE_ID=i-xxx AWS_REGION=ap-southeast-1 ./scripts/aws/lab_notion_oneliner_ssm.sh

set -euo pipefail

LAB_INSTANCE_ID="${LAB_INSTANCE_ID:-i-0d82c172235770a0d}"
REGION="${AWS_REGION:-ap-southeast-1}"
REPO=/home/ubuntu/automated-trading-platform
# Compose on LAB is run from repo root; override with BACKEND=.../backend if your setup differs.
BACKEND="${BACKEND:-/home/ubuntu/automated-trading-platform}"
NOTION_DB_ID=eb90cfa139f94724a8b476315908510a
SSM_NOTION_KEY="/automated-trading-platform/lab/notion/api_key"

# Fail fast if the SSM parameter does not exist (avoids opaque remote failure).
if ! aws ssm get-parameter --name "$SSM_NOTION_KEY" --with-decryption --region "$REGION" --query Parameter.Value --output text >/dev/null 2>&1; then
  echo "ERROR: SSM parameter not found: $SSM_NOTION_KEY" >&2
  echo "Create it so LAB can read the Notion secret, e.g.:" >&2
  echo "  ./scripts/aws/store_lab_notion_api_key_ssm.sh" >&2
  echo "Or: aws ssm put-parameter --name $SSM_NOTION_KEY --value \"<your-notion-secret>\" --type SecureString --region $REGION" >&2
  exit 1
fi

# Single shell block as ubuntu so NOTION_SECRET persists. Use semicolons to avoid newline mangling in SSM.
INLINE="sudo -u ubuntu bash -c 'set -e; \
NOTION_SECRET=\$(aws ssm get-parameter --name $SSM_NOTION_KEY --with-decryption --region $REGION --query Parameter.Value --output text); \
grep -q \"^NOTION_API_KEY=\" $REPO/.env.aws && sed -i \"s|^NOTION_API_KEY=.*|NOTION_API_KEY=\$NOTION_SECRET|\" $REPO/.env.aws || printf \"\\\\nNOTION_API_KEY=%s\\\\n\" \"\$NOTION_SECRET\" >> $REPO/.env.aws; \
grep -q \"^NOTION_TASK_DB=\" $REPO/.env.aws && sed -i \"s|^NOTION_TASK_DB=.*|NOTION_TASK_DB=$NOTION_DB_ID|\" $REPO/.env.aws || printf \"\\\\nNOTION_TASK_DB=$NOTION_DB_ID\\\\n\" >> $REPO/.env.aws; \
cd $REPO && bash scripts/aws/render_runtime_env.sh; \
cd $BACKEND && docker compose --profile aws up -d backend-aws; \
sleep 15; \
cd $BACKEND && docker compose --profile aws exec -T backend-aws sh -c '\''if [ -n \"\$NOTION_API_KEY\" ]; then echo NOTION_API_KEY=present; else echo NOTION_API_KEY=not present; fi'\''; \
cd $BACKEND && docker compose --profile aws exec -T backend-aws sh -c '\''if [ -n \"\$NOTION_TASK_DB\" ]; then echo NOTION_TASK_DB=present; else echo NOTION_TASK_DB=not present; fi'\''; \
cd $BACKEND && docker compose --profile aws exec -T backend-aws printenv NOTION_TASK_DB; \
cd $REPO && ./scripts/run_notion_task_pickup.sh; \
'"

# One command = one shell, so NOTION_SECRET persists. JSON array with single string (newlines ok in JSON).
CMD_JSON=$(printf '%s' "$INLINE" | python3 -c "
import sys, json
s = sys.stdin.read()
print(json.dumps([s]))
")

CMD_ID=$(aws ssm send-command \
  --instance-ids "$LAB_INSTANCE_ID" \
  --region "$REGION" \
  --document-name "AWS-RunShellScript" \
  --timeout-seconds 600 \
  --parameters "commands=$CMD_JSON" \
  --query 'Command.CommandId' --output text)

echo "Command ID: $CMD_ID"
echo "Poll: aws ssm get-command-invocation --command-id $CMD_ID --instance-id $LAB_INSTANCE_ID --region $REGION --query 'StandardOutputContent' --output text"
echo "Waiting 90s then printing output..."
sleep 90
aws ssm get-command-invocation --command-id "$CMD_ID" --instance-id "$LAB_INSTANCE_ID" --region "$REGION" --query 'StandardOutputContent' --output text 2>/dev/null || true
echo ""
echo "Status: $(aws ssm get-command-invocation --command-id "$CMD_ID" --instance-id "$LAB_INSTANCE_ID" --region "$REGION" --query 'Status' --output text 2>/dev/null || echo '?')"

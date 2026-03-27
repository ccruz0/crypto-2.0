#!/usr/bin/env bash
# Verify Telegram /task stabilization in production.
#
# Run via SSM:
#   aws ssm send-command --instance-ids i-087953603011543c5 --document-name AWS-RunShellScript \
#     --parameters 'commands=["cd /home/ubuntu/crypto-2.0 2>/dev/null || cd /home/ubuntu/crypto-2.0 || true","bash scripts/aws/verify_telegram_task_production.sh"]' \
#     --region ap-southeast-1
#
# Or run directly on EC2:
#   cd /home/ubuntu/crypto-2.0 && bash scripts/aws/verify_telegram_task_production.sh

set -euo pipefail

REPO="${1:-/home/ubuntu/crypto-2.0}"
[[ -d "$REPO" ]] || REPO="/home/ubuntu/crypto-2.0"
cd "$REPO" 2>/dev/null || { echo "Repo not found"; exit 1; }

echo "=== TELEGRAM /task PRODUCTION VERIFICATION ==="
echo ""

# 1. Single poller
echo "--- 1. TELEGRAM POLLER STATUS ---"
bash backend/scripts/diag/detect_telegram_consumers.sh 2>/dev/null || true
echo ""

# 2. Canary RUN_TELEGRAM_POLLER
echo "--- 2. CANARY RUN_TELEGRAM_POLLER ---"
canary_poller=$(docker compose --profile aws exec -T backend-aws-canary printenv RUN_TELEGRAM_POLLER 2>/dev/null || echo "N/A")
echo "backend-aws-canary RUN_TELEGRAM_POLLER=${canary_poller:-N/A}"
if [[ "${canary_poller:-true}" == "false" ]]; then
  echo "  OK: Canary does not poll"
else
  echo "  WARN: Canary should have RUN_TELEGRAM_POLLER=false"
fi
echo ""

# 3. New logs (token_source, chat_id, handler)
echo "--- 3. RECENT [TG] LOGS (token_source, chat_id, handler) ---"
docker compose --profile aws logs backend-aws --tail=200 2>/dev/null | grep -E '\[TG\]\[UPDATE\]|\[TG\]\[ROUTER\]|\[TG\]\[TASK\]' | tail -20 || echo "  (no matches - send /task in ATP Control to generate)"
echo ""

# 4. Old "low impact" message - must NOT appear
echo "--- 4. OLD MESSAGE CHECK (must be empty) ---"
low_count=$(docker compose --profile aws logs backend-aws --tail=500 2>/dev/null | grep -c "low impact and was not created" 2>/dev/null || echo "0")
echo "Occurrences of 'low impact and was not created' in last 500 lines: $low_count"
if [[ "$low_count" -gt 0 ]]; then
  echo "  FAIL: Old message still present - deploy current code"
else
  echo "  OK: Old message not in recent logs"
fi
echo ""

# 5. NOTION env in backend-aws
echo "--- 5. NOTION CONFIG IN RUNTIME ---"
notion_key=$(docker compose --profile aws exec -T backend-aws printenv NOTION_API_KEY 2>/dev/null || echo "")
notion_db=$(docker compose --profile aws exec -T backend-aws printenv NOTION_TASK_DB 2>/dev/null || echo "")
if [[ -n "${notion_key:-}" ]]; then
  echo "  NOTION_API_KEY: present (${#notion_key} chars)"
else
  echo "  NOTION_API_KEY: NOT SET"
fi
if [[ -n "${notion_db:-}" ]]; then
  echo "  NOTION_TASK_DB: $notion_db"
else
  echo "  NOTION_TASK_DB: NOT SET"
fi
echo ""

# 6. runtime.env has NOTION?
echo "--- 6. secrets/runtime.env NOTION ---"
grep -E '^NOTION_' secrets/runtime.env 2>/dev/null | sed 's/=.*/=***/' || echo "  (not found or file missing)"
echo ""

echo "=== NEXT: Send '/task test deployment verification' in ATP Control ==="
echo "Then re-run this script or: docker compose --profile aws logs backend-aws --tail=50 | grep -E '\[TG\]\[TASK\]|token_source'"

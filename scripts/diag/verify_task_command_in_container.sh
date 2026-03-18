#!/usr/bin/env bash
# Verify /task command is present in the running backend-aws container.
# Run on EC2 (or where backend-aws runs) to confirm deployed code has /task handler.
#
# Usage:
#   ./scripts/diag/verify_task_command_in_container.sh
#   # Or via SSM:
#   aws ssm send-command --instance-ids i-087953603011543c5 --document-name AWS-RunShellScript \
#     --parameters 'commands=["cd /home/ubuntu/automated-trading-platform 2>/dev/null || cd /home/ubuntu/crypto-2.0 || exit 1","bash scripts/diag/verify_task_command_in_container.sh"]' \
#     --region ap-southeast-1

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"

echo "=== Verify /task in backend-aws ==="
echo ""

# 1. Check handler_name == "task" (router fallback)
if docker compose --profile aws exec -T backend-aws grep -q 'handler_name == "task"' /app/app/services/telegram_commands.py 2>/dev/null; then
  echo "✅ Router fallback (handler_name == \"task\") present"
else
  echo "❌ Router fallback NOT found - /task may not be recognized"
fi

# 2. Check text_lower.startswith("/task")
if docker compose --profile aws exec -T backend-aws grep -q 'text_lower.startswith("/task")' /app/app/services/telegram_commands.py 2>/dev/null; then
  echo "✅ text_lower.startswith(\"/task\") present"
else
  echo "❌ text_lower /task check NOT found"
fi

# 3. Check setMyCommands includes task
if docker compose --profile aws exec -T backend-aws grep -q '"command": "task"' /app/app/services/telegram_commands.py 2>/dev/null; then
  echo "✅ setMyCommands includes task"
else
  echo "❌ setMyCommands task NOT found"
fi

# 4. Check send_help_message includes /task
if docker compose --profile aws exec -T backend-aws grep -q '/task' /app/app/services/telegram_commands.py 2>/dev/null; then
  echo "✅ /task referenced in telegram_commands.py"
else
  echo "❌ /task NOT found in telegram_commands.py"
fi

echo ""
echo "If any ❌ above: rebuild with --no-cache and redeploy."
echo "See: docs/runbooks/ATP_CONTROL_ARCHITECTURE_AND_TASK_FIX.md"

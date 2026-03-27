#!/usr/bin/env bash
# Free disk on PROD EC2 via SSM: runs infra/cleanup_disk.sh (Docker prune, log truncate, journal, apt).
# Does NOT remove named volumes (Postgres data safe). See infra/cleanup_disk.sh.
#
# Usage:
#   ./scripts/aws/prod_free_disk_via_ssm.sh
#   ATP_INSTANCE_ID=i-xxx AWS_REGION=ap-southeast-1 ./scripts/aws/prod_free_disk_via_ssm.sh
#
# Optional — more space (removes ALL unused images + full build cache; still no volumes):
#   AGGRESSIVE=1 ./scripts/aws/prod_free_disk_via_ssm.sh

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"

INSTANCE_ID="${ATP_INSTANCE_ID:-i-087953603011543c5}"
REGION="${AWS_REGION:-ap-southeast-1}"
AGGRESSIVE="${AGGRESSIVE:-0}"
export AWS_REGION="$REGION"

echo "=== PROD free disk via SSM (instance $INSTANCE_ID) ==="
echo "  AGGRESSIVE=$AGGRESSIVE"
echo ""

STATUS=$(aws ssm describe-instance-information --region "$REGION" \
  --filters "Key=InstanceIds,Values=$INSTANCE_ID" \
  --query 'InstanceInformationList[0].PingStatus' --output text 2>/dev/null || echo "NotFound")
[[ -z "$STATUS" || "$STATUS" == "None" ]] && STATUS="NotFound"
if [[ "$STATUS" != "Online" ]]; then
  echo "SSM PingStatus: $STATUS — instance must be Online."
  exit 1
fi

GIT_PULL_PREFIX='export HOME=/home/ubuntu; git config --global --add safe.directory /home/ubuntu/crypto-2.0 2>/dev/null || true; git config --global --add safe.directory /home/ubuntu/crypto-2.0 2>/dev/null || true; '
GIT_FETCH_CMD="${GIT_PULL_PREFIX}rm -f .git/refs/remotes/origin/main 2>/dev/null || true; git fetch origin main && git reset --hard FETCH_HEAD 2>/dev/null || git reset --hard origin/main 2>/dev/null || git pull origin main 2>/dev/null || true"

export GIT_FETCH_CMD
export AGGRESSIVE
PARAMS="commands=$(python3 <<'PY'
import json, os
git_fetch = os.environ["GIT_FETCH_CMD"]
aggressive = os.environ.get("AGGRESSIVE", "0") == "1"
cmds = [
    "set -e",
    "cd /home/ubuntu/crypto-2.0 2>/dev/null || cd /home/ubuntu/crypto-2.0 || exit 1",
    git_fetch,
    "chmod +x infra/cleanup_disk.sh 2>/dev/null || true",
    "bash infra/cleanup_disk.sh",
]
if aggressive:
    cmds.append(
        "docker builder prune -af 2>/dev/null || true; "
        "docker image prune -af 2>/dev/null || true; "
        'echo "AGGRESSIVE docker prune done"'
    )
cmds.append("echo === df after ===; df -h /")
print(json.dumps(cmds), end="")
PY
)"

CMD=$(aws ssm send-command \
  --instance-ids "$INSTANCE_ID" \
  --region "$REGION" \
  --document-name "AWS-RunShellScript" \
  --parameters "$PARAMS" \
  --timeout-seconds 600 \
  --query 'Command.CommandId' --output text 2>&1)

if [[ -z "$CMD" ]]; then
  echo "send-command failed: empty CommandId"
  exit 1
fi
case "$CMD" in
  *"Error"*|*"error"*)
    echo "send-command failed: $CMD"
    exit 1
    ;;
esac

echo "CommandId: $CMD (polling up to 600s)..."
for i in $(seq 1 600); do
  S=$(aws ssm get-command-invocation --command-id "$CMD" --instance-id "$INSTANCE_ID" --region "$REGION" --query 'Status' --output text 2>/dev/null || echo Pending)
  if [[ "$S" == "Success" ]]; then
    echo ""
    aws ssm get-command-invocation --command-id "$CMD" --instance-id "$INSTANCE_ID" --region "$REGION" --query 'StandardOutputContent' --output text 2>/dev/null || true
    echo ""
    echo "[DONE]"
    exit 0
  fi
  if [[ "$S" == "Failed" || "$S" == "Cancelled" ]]; then
    echo "Status: $S"
    aws ssm get-command-invocation --command-id "$CMD" --instance-id "$INSTANCE_ID" --region "$REGION" --query 'StandardOutputContent' --output text 2>/dev/null || true
    aws ssm get-command-invocation --command-id "$CMD" --instance-id "$INSTANCE_ID" --region "$REGION" --query 'StandardErrorContent' --output text 2>/dev/null || true
    exit 1
  fi
  sleep 1
done
echo "Timeout polling SSM."
exit 1

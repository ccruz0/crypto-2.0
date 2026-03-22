#!/usr/bin/env bash
# Repair OpenClaw on LAB using AWS SSM Run Command (no interactive SSH).
# 1) LAB: optional git pull + scripts/openclaw/repair_openclaw_lab_on_instance.sh
# 2) PROD: curl -I to LAB private IP:8080 (cross-VPC reachability + SG check)
#
# Usage (from laptop with AWS CLI):
#   ./scripts/openclaw/repair_openclaw_lab_via_ssm.sh
#
# Env:
#   LAB_INSTANCE_ID / OPENCLAW_LAB_INSTANCE_ID  (default i-0d82c172235770a0d)
#   DASHBOARD_INSTANCE_ID / ATP_INSTANCE_ID     (default i-087953603011543c5)
#   AWS_REGION (default ap-southeast-1)
#   ATP_REPO_PATH (default /home/ubuntu/automated-trading-platform)
#   LAB_PRIVATE_IP (default 172.31.3.214)
#   OPENCLAW_PORT (default 8080)
#   SKIP_GIT_PULL=1   — do not pull before repair
#   SKIP_PROD_CURL=1  — skip validation from PROD via SSM
#   OPENCLAW_SSM_EMBED_REPAIR=1 — ship repair_openclaw_lab_on_instance.sh via chunked base64 (no git pull needed)
#   SSM_TIMEOUT_SECONDS (default 1800), SSM_LAB_WAIT_SECONDS (default 1800), SSM_PROD_WAIT_SECONDS (default 90)
set -euo pipefail

AWS_REGION="${AWS_REGION:-ap-southeast-1}"
LAB_INSTANCE_ID="${LAB_INSTANCE_ID:-${OPENCLAW_LAB_INSTANCE_ID:-i-0d82c172235770a0d}}"
DASHBOARD_INSTANCE_ID="${DASHBOARD_INSTANCE_ID:-${ATP_INSTANCE_ID:-i-087953603011543c5}}"
REPO="${ATP_REPO_PATH:-/home/ubuntu/automated-trading-platform}"
LAB_IP="${LAB_PRIVATE_IP:-172.31.3.214}"
PORT="${OPENCLAW_PORT:-8080}"

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$REPO_ROOT"

if ! command -v aws &>/dev/null; then
  echo "AWS CLI required."
  exit 1
fi

ssm_ping() {
  aws ssm describe-instance-information --region "$AWS_REGION" \
    --filters "Key=InstanceIds,Values=$1" \
    --query 'InstanceInformationList[0].PingStatus' --output text 2>/dev/null || echo "NotFound"
}

wait_invocation() {
  local cmd_id="$1" iid="$2" max_secs="${3:-120}"
  local status="Pending" elapsed=0
  while [[ "$elapsed" -lt "$max_secs" ]]; do
    status=$(aws ssm get-command-invocation \
      --command-id "$cmd_id" \
      --instance-id "$iid" \
      --region "$AWS_REGION" \
      --query "Status" --output text 2>/dev/null || echo "Pending")
    [[ "$status" == "Success" || "$status" == "Failed" || "$status" == "Cancelled" ]] && break
    sleep 2
    elapsed=$((elapsed + 2))
  done
  echo "=== SSM Status ($iid): $status ==="
  aws ssm get-command-invocation \
    --command-id "$cmd_id" \
    --instance-id "$iid" \
    --region "$AWS_REGION" \
    --query '[StandardOutputContent,StandardErrorContent]' \
    --output text 2>/dev/null || true
  [[ "$status" == "Success" ]]
}

echo "======== OpenClaw LAB repair via SSM ========"
echo "LAB=$LAB_INSTANCE_ID  PROD(dashboard)=$DASHBOARD_INSTANCE_ID  region=$AWS_REGION"
echo "LAB_PRIVATE_IP=$LAB_IP  PORT=$PORT  REPO_ON_LAB=$REPO"
echo ""

st=$(ssm_ping "$LAB_INSTANCE_ID")
echo "SSM PingStatus LAB $LAB_INSTANCE_ID: $st"
if [[ "$st" != "Online" ]]; then
  echo "LAB instance is not Online for SSM. Fix IAM / SSM agent / endpoints, or set LAB_INSTANCE_ID."
  exit 1
fi

if [[ "${SKIP_PROD_CURL:-0}" != "1" ]]; then
  stp=$(ssm_ping "$DASHBOARD_INSTANCE_ID")
  echo "SSM PingStatus PROD $DASHBOARD_INSTANCE_ID: $stp"
  if [[ "$stp" != "Online" ]]; then
    echo "PROD not Online — cannot run cross-host curl. Re-run with SKIP_PROD_CURL=1 to repair LAB only."
    exit 1
  fi
fi

# AWS-RunShellScript uses /bin/sh (dash) — use bash -lc for pipefail and strict mode.
SCRIPT_ON_LAB="$REPO/scripts/openclaw/repair_openclaw_lab_on_instance.sh"
LOCAL_SCRIPT="$REPO_ROOT/scripts/openclaw/repair_openclaw_lab_on_instance.sh"

build_lab_params_embedded() {
  SCRIPT_PATH="$LOCAL_SCRIPT" REPO="$REPO" PORT="$PORT" GIT_PULL="${GIT_PULL:-0}" PRUNE="${OPENCLAW_LAB_DOCKER_PRUNE:-0}" python3 <<'PY'
import base64, json, os
from pathlib import Path

repo = os.environ["REPO"]
port = os.environ["PORT"]
prune = os.environ.get("PRUNE", "0")
b64 = base64.b64encode(Path(os.environ["SCRIPT_PATH"]).read_bytes()).decode("ascii")
commands = [
    "set -eu",
    "rm -f /tmp/openclaw_lab_repair.b64 /tmp/openclaw_lab_repair.sh",
    ": > /tmp/openclaw_lab_repair.b64",
]
step = 900
for i in range(0, len(b64), step):
    chunk = b64[i : i + step]
    commands.append("printf %s >> /tmp/openclaw_lab_repair.b64 " + json.dumps(chunk))
commands.extend(
    [
        "base64 -d /tmp/openclaw_lab_repair.b64 > /tmp/openclaw_lab_repair.sh",
        "chmod +x /tmp/openclaw_lab_repair.sh",
        f"export ATP_REPO_PATH={repo} OPENCLAW_PORT={port} OPENCLAW_LAB_DOCKER_PRUNE={prune}",
    ]
)
if os.environ.get("GIT_PULL") == "1":
    commands.append(
        f'sudo -u ubuntu bash -lc "cd {repo} && git fetch origin main && git checkout main && git pull origin main" || true'
    )
commands.append("bash /tmp/openclaw_lab_repair.sh")
print(json.dumps({"commands": commands}))
PY
}

if [[ "${OPENCLAW_SSM_EMBED_REPAIR:-0}" == "1" ]]; then
  if [[ ! -f "$LOCAL_SCRIPT" ]]; then
    echo "Missing $LOCAL_SCRIPT"
    exit 1
  fi
  if [[ "${SKIP_GIT_PULL:-0}" == "1" ]]; then
    GIT_PULL=0 LAB_PARAMS="$(build_lab_params_embedded)"
  else
    GIT_PULL=1 LAB_PARAMS="$(build_lab_params_embedded)"
  fi
  echo "Using OPENCLAW_SSM_EMBED_REPAIR=1 (script from local repo, base64 over SSM)."
elif [[ "${SKIP_GIT_PULL:-0}" == "1" ]]; then
  LAB_PARAMS=$(cat <<EOF
{
  "commands": [
    "bash -lc 'set -euo pipefail; export ATP_REPO_PATH=$REPO OPENCLAW_PORT=$PORT OPENCLAW_LAB_DOCKER_PRUNE=${OPENCLAW_LAB_DOCKER_PRUNE:-0}; bash $SCRIPT_ON_LAB'"
  ]
}
EOF
)
else
  LAB_PARAMS=$(cat <<EOF
{
  "commands": [
    "bash -lc 'set -euo pipefail; export ATP_REPO_PATH=$REPO OPENCLAW_PORT=$PORT OPENCLAW_LAB_DOCKER_PRUNE=${OPENCLAW_LAB_DOCKER_PRUNE:-0}; sudo -u ubuntu bash -lc \"cd $REPO && git fetch origin main && git checkout main && git pull origin main\" || true; bash $SCRIPT_ON_LAB'"
  ]
}
EOF
)
fi

echo "=== Sending LAB repair (SSM) ==="
lab_cmd=$(aws ssm send-command \
  --instance-ids "$LAB_INSTANCE_ID" \
  --document-name "AWS-RunShellScript" \
  --parameters "$LAB_PARAMS" \
  --region "$AWS_REGION" \
  --timeout-seconds "${SSM_TIMEOUT_SECONDS:-1800}" \
  --output text \
  --query "Command.CommandId")

lab_ok=0
if wait_invocation "$lab_cmd" "$LAB_INSTANCE_ID" "${SSM_LAB_WAIT_SECONDS:-1800}"; then lab_ok=1; fi
echo ""

if [[ "$lab_ok" != "1" ]]; then
  echo "OPENCLAW_SSM_LAB_REPAIR_FAILED=1"
  echo "If the script was missing on LAB, push this branch to main and re-run, or bootstrap the file onto LAB."
  exit 1
fi

if [[ "${SKIP_PROD_CURL:-0}" == "1" ]]; then
  echo "SKIP_PROD_CURL=1 — done after LAB repair."
  exit 0
fi

PROD_PARAMS=$(cat <<EOF
{
  "commands": [
    "echo \"=== PROD curl to LAB upstream ($LAB_IP:$PORT) ===\"",
    "curl -sS -I --max-time 5 http://$LAB_IP:$PORT/ 2>&1 | head -25 || true"
  ]
}
EOF
)

echo "=== PROD validation: curl -I --max-time 5 http://$LAB_IP:$PORT/ (from dashboard) ==="
prod_cmd=$(aws ssm send-command \
  --instance-ids "$DASHBOARD_INSTANCE_ID" \
  --document-name "AWS-RunShellScript" \
  --parameters "$PROD_PARAMS" \
  --region "$AWS_REGION" \
  --timeout-seconds 60 \
  --output text \
  --query "Command.CommandId")

wait_invocation "$prod_cmd" "$DASHBOARD_INSTANCE_ID" "${SSM_PROD_WAIT_SECONDS:-90}" || true
echo ""

echo "======== Interpretation ========"
echo "• LAB output ends with OPENCLAW_LAB_REPAIR_EXIT=0: listener + local curl succeeded on LAB."
echo "• PROD curl shows HTTP headers (e.g. 401/200): **routing OK**; nginx /openclaw/ should reach upstream."
echo "• PROD curl timeout/refused but LAB local OK: **security group or NACL** — add LAB inbound TCP $PORT from PROD private IP or PROD security group; confirm same-VPC routing."
echo "• LAB failed at docker info: **Docker daemon** — systemctl start docker on LAB."
echo "• LAB failed compose / no container: **wrong path or image** — verify repo at $REPO and docker-compose.openclaw.yml."
echo ""
echo "Done."

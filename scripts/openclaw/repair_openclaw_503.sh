#!/usr/bin/env bash
# One entrypoint: repair OpenClaw 503/504 (upstream dead or wrong port) from your Mac.
# Tries EC2 Instance Connect + SSH first. If you get "Permission denied (publickey)", use SSM instead (see below).
#
# Env (optional, defaults match this repo):
#   ATP_INSTANCE_ID       Dashboard EC2 (nginx)
#   OPENCLAW_LAB_INSTANCE_ID   LAB EC2 (docker-compose.openclaw.yml)
#   LAB_PRIVATE_IP        LAB private IP (default 172.31.3.214)
#   OPENCLAW_PORT         Host port OpenClaw publishes (default 8080 per docker-compose.openclaw.yml)
#
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
if ! "$ROOT/fix_504_via_eice.sh" "$@"; then
  echo ""
  echo "=== SSH failed (common: security group blocks :22 from home, or wrong key). Use SSM (no SSH from Mac): ==="
  echo "  $ROOT/repair_openclaw_503_via_ssm.sh"
  exit 1
fi

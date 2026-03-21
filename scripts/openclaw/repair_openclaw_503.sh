#!/usr/bin/env bash
# One entrypoint: repair OpenClaw 503/504 (upstream dead or wrong port) from your Mac.
# Requires: AWS CLI, permission for EC2 Instance Connect on dashboard + lab instance IDs.
#
# Does: git pull on dashboard → deploy nginx from repo → normalize proxy → start OpenClaw on LAB via SSH from dashboard.
#
# Env (optional, defaults match this repo):
#   ATP_INSTANCE_ID       Dashboard EC2 (nginx)
#   OPENCLAW_LAB_INSTANCE_ID   LAB EC2 (docker-compose.openclaw.yml)
#   LAB_PRIVATE_IP        LAB private IP (default 172.31.3.214)
#   OPENCLAW_PORT         Host port OpenClaw publishes (default 8080 per docker-compose.openclaw.yml)
#
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
exec "$ROOT/fix_504_via_eice.sh" "$@"

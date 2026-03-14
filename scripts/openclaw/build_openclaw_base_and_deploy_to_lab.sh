#!/usr/bin/env bash
# Build OpenClaw base image (with gateway model contract), push to GHCR, build ATP wrapper,
# push wrapper, then deploy to LAB via SSM. Run from your Mac with Docker running.
#
# Prerequisites:
#   - Docker running
#   - Logged into GHCR: docker login ghcr.io -u ccruz0
#   - OpenClaw repo at ../openclaw (or set OPENCLAW_REPO_PATH)
#
# Usage:
#   ./scripts/openclaw/build_openclaw_base_and_deploy_to_lab.sh
#   OPENCLAW_REPO_PATH=/path/to/openclaw ./scripts/openclaw/build_openclaw_base_and_deploy_to_lab.sh
#
set -euo pipefail

REPO_ROOT="${REPO_ROOT:-$(cd "$(dirname "$0")/../.." && pwd)}"
OPENCLAW_REPO_PATH="${OPENCLAW_REPO_PATH:-$REPO_ROOT/../openclaw}"
OPENCLAW_IMAGE="${OPENCLAW_IMAGE:-ghcr.io/ccruz0/openclaw:latest}"
LAB_INSTANCE_ID="${LAB_INSTANCE_ID:-i-0d82c172235770a0d}"
AWS_REGION="${AWS_REGION:-ap-southeast-1}"

if [[ ! -d "$OPENCLAW_REPO_PATH" ]]; then
  echo "ERROR: OpenClaw repo not found at $OPENCLAW_REPO_PATH. Set OPENCLAW_REPO_PATH." 1>&2
  exit 1
fi

echo "==> 1/4 Building OpenClaw base image (linux/amd64) from $OPENCLAW_REPO_PATH"
docker build --platform linux/amd64 -t "$OPENCLAW_IMAGE" "$OPENCLAW_REPO_PATH"

echo ""
echo "==> 2/4 Pushing base image to GHCR"
docker push "$OPENCLAW_IMAGE"

echo ""
echo "==> 3/4 Building ATP wrapper (uses new base) and pushing"
cd "$REPO_ROOT"
docker build -f openclaw/Dockerfile.openclaw -t openclaw-with-origins:latest .
docker tag openclaw-with-origins:latest "$OPENCLAW_IMAGE"
docker push "$OPENCLAW_IMAGE"

echo ""
echo "==> 4/4 Deploying on LAB ($LAB_INSTANCE_ID) via SSM"
bash "$REPO_ROOT/scripts/openclaw/deploy_openclaw_lab_from_mac.sh" deploy

echo ""
echo "==> Re-run gateway model diagnostic to confirm 400 for unsupported model:"
echo "   bash $REPO_ROOT/scripts/openclaw/run_gateway_model_diagnostic_via_ssm.sh"

#!/usr/bin/env bash
# Grant OpenClaw access: print commands to run on LAB (token + restart) or open SSM to LAB.
# Usage:
#   ./scripts/openclaw/grant_openclaw_access_lab.sh           # print commands
#   ./scripts/openclaw/grant_openclaw_access_lab.sh --run    # open SSM session to LAB (then run the printed commands there)
# Run from repo root. Requires AWS CLI and SSM Session Manager plugin for --run.
# See: docs/openclaw/OPENCLAW_ACCESS_CRYPTO_AND_GITHUB.md

set -euo pipefail
LAB_ID="${OPENCLAW_LAB_INSTANCE_ID:-i-0d82c172235770a0d}"
REGION="${AWS_REGION:-ap-southeast-1}"

print_commands() {
  echo "=== Connect to LAB (run from your Mac) ==="
  echo ""
  echo "  aws ssm start-session --target $LAB_ID --region $REGION"
  echo ""
  echo "=== Then on LAB: create token file (paste your GitHub fine-grained PAT when prompted) ==="
  echo ""
  cat << 'ONLAB'
mkdir -p ~/secrets && chmod 700 ~/secrets
touch ~/secrets/openclaw_token && chmod 600 ~/secrets/openclaw_token
read -r -s -p 'Paste GitHub fine-grained PAT: ' TOKEN && echo -n "$TOKEN" > ~/secrets/openclaw_token && unset TOKEN
ONLAB
  echo ""
  echo "=== Then on LAB: restart OpenClaw ==="
  echo ""
  echo "  cd ~/crypto-2.0 && docker compose -f docker-compose.openclaw.yml up -d --force-recreate"
  echo ""
  echo "=== Verify (on LAB) ==="
  echo ""
  echo "  docker exec openclaw env | grep OPENCLAW_TOKEN_FILE"
  echo "  # Expected: OPENCLAW_TOKEN_FILE=/run/secrets/openclaw_token"
}

if [[ "${1:-}" == "--run" ]]; then
  echo "Opening SSM session to LAB ($LAB_ID). Once connected, run the token and restart commands (see below or run this script without --run to print them)."
  echo ""
  print_commands
  echo ""
  echo "--- Connecting now ---"
  exec aws ssm start-session --target "$LAB_ID" --region "$REGION"
else
  print_commands
fi

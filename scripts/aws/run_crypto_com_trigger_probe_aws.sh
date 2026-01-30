#!/usr/bin/env bash
set -euo pipefail
set +x 2>/dev/null || true

# Run the standalone Crypto.com trigger probe on the AWS host using real credentials.
#
# Safety:
# - Runs in a one-off container (does not restart backend service)
# - Bind-mounts the local probe file into the container
# - Bind-mounts /tmp so the JSONL output persists on the host for later inspection
#
# Usage (defaults match the requested execution):
#   bash scripts/aws/run_crypto_com_trigger_probe_aws.sh
#
# Override args:
#   INSTRUMENT=ETH_USDT SIDE=SELL QTY=0.003 REF_PRICE=2950 MAX_VARIANTS=50 bash scripts/aws/run_crypto_com_trigger_probe_aws.sh
#
# To download JSONL output from AWS host:
#   The script will print ready-to-copy scp commands after the probe completes.
#   You can also set SSH_KEY_PATH and SSH_USER env vars to customize the commands.

REMOTE_HOST="${REMOTE_HOST:-hilovivo-aws}"
REMOTE_REPO="${REMOTE_REPO:-/home/ubuntu/automated-trading-platform}"
SSH_USER="${SSH_USER:-ec2-user}"
SSH_KEY_PATH="${SSH_KEY_PATH:-}"

INSTRUMENT="${INSTRUMENT:-ETH_USDT}"
SIDE="${SIDE:-SELL}"
QTY="${QTY:-0.003}"
REF_PRICE="${REF_PRICE:-2950}"
MAX_VARIANTS="${MAX_VARIANTS:-50}"

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PROBE_LOCAL="$ROOT_DIR/backend/app/tools/crypto_com_trigger_probe.py"

if [[ ! -f "$PROBE_LOCAL" ]]; then
  echo "ERROR: probe file not found at $PROBE_LOCAL" >&2
  exit 2
fi

# Helper function to build scp command with optional SSH key
build_scp_cmd() {
  local remote_path="$1"
  local local_path="$2"
  local cmd="scp"
  if [[ -n "$SSH_KEY_PATH" ]]; then
    cmd="$cmd -i \"$SSH_KEY_PATH\""
  fi
  cmd="$cmd \"${SSH_USER}@${REMOTE_HOST}:${remote_path}\" \"${local_path}\""
  echo "$cmd"
}

echo "== Sync probe to AWS host =="
scp "$PROBE_LOCAL" "${REMOTE_HOST}:${REMOTE_REPO}/backend/app/tools/crypto_com_trigger_probe.py"

echo "== Run probe (one-off container) =="
PROBE_OUTPUT=$(ssh "${REMOTE_HOST}" "set -e; cd \"${REMOTE_REPO}\"; \
  docker compose --profile aws run --rm \
    -v /tmp:/tmp \
    -v \"${REMOTE_REPO}/backend/app/tools/crypto_com_trigger_probe.py:/app/app/tools/crypto_com_trigger_probe.py:ro\" \
    backend-aws \
    python3 -m app.tools.crypto_com_trigger_probe \
      --instrument \"${INSTRUMENT}\" \
      --side \"${SIDE}\" \
      --qty \"${QTY}\" \
      --ref-price \"${REF_PRICE}\" \
      --max-variants \"${MAX_VARIANTS}\" \
      --dry-run" 2>&1)

echo "$PROBE_OUTPUT"

# Extract correlation_id from probe output
CORRELATION_ID=$(echo "$PROBE_OUTPUT" | grep -E "^correlation_id:" | sed -E 's/^correlation_id: +//' | head -1 | tr -d '[:space:]')

# Print download commands if correlation_id was found
if [[ -n "$CORRELATION_ID" ]]; then
  echo ""
  echo "== Download JSONL =="
  echo ""
  echo "# Download specific correlation_id file:"
  SPECIFIC_CMD=$(build_scp_cmd "/tmp/crypto_trigger_probe_${CORRELATION_ID}.jsonl" "/tmp/")
  echo "$SPECIFIC_CMD"
  echo ""
  echo "# Download all probe JSONL files (wildcard):"
  WILDCARD_CMD=$(build_scp_cmd "/tmp/crypto_trigger_probe_*.jsonl" "/tmp/")
  echo "$WILDCARD_CMD"
  echo ""
  echo "# To use a custom SSH key, set SSH_KEY_PATH before running this script:"
  echo "#   SSH_KEY_PATH=~/.ssh/id_rsa bash scripts/aws/run_crypto_com_trigger_probe_aws.sh"
else
  echo ""
  echo "WARNING: Could not extract correlation_id from probe output."
  echo "You can still download JSONL files manually using:"
  WILDCARD_CMD=$(build_scp_cmd "/tmp/crypto_trigger_probe_*.jsonl" "/tmp/")
  echo "$WILDCARD_CMD"
fi


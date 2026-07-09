#!/usr/bin/env bash
# Print the canonical production git repo root on EC2.
# Prefer crypto-2.0 (active clone); fall back to automated-trading-platform only if it is a git repo.
#
# Usage:
#   REPO=$(bash scripts/aws/resolve_prod_repo_root.sh)
#   cd "$REPO"
#
# For SSM one-liners (no script on host yet):
#   eval "$(bash scripts/aws/resolve_prod_repo_root.sh --cd-snippet)"

set -euo pipefail

resolve_prod_repo_root() {
  if [[ -d /home/ubuntu/crypto-2.0/.git ]]; then
    printf '%s\n' /home/ubuntu/crypto-2.0
    return 0
  fi
  if [[ -d /home/ubuntu/automated-trading-platform/.git ]]; then
    printf '%s\n' /home/ubuntu/automated-trading-platform
    return 0
  fi
  return 1
}

if [[ "${1:-}" == "--cd-snippet" ]]; then
  cat <<'EOF'
if [ -d /home/ubuntu/crypto-2.0/.git ]; then cd /home/ubuntu/crypto-2.0; elif [ -d /home/ubuntu/automated-trading-platform/.git ]; then cd /home/ubuntu/automated-trading-platform; else echo "ERR: no production git repository found" >&2; exit 1; fi
EOF
  exit 0
fi

if ! resolve_prod_repo_root; then
  echo "ERROR: no production git repository found (expected crypto-2.0 or automated-trading-platform with .git)" >&2
  exit 1
fi

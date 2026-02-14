#!/usr/bin/env bash
# Bring up AWS stack and run final EC2 hard verification. Exit code = verification script exit code.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
cd "${REPO_ROOT}"

docker compose --profile aws up -d db backend-aws frontend-aws
bash "${SCRIPT_DIR}/final_ec2_hard_verification.sh"
exit $?

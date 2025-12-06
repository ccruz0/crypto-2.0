#!/usr/bin/env bash
set -euo pipefail

# Pre-deployment wrapper - validates SSH system and runs DRY_RUN simulations
#
# Usage:
#   ./scripts/pre_deploy_check.sh
#
# Exits non-zero if any validation fails.

ROOT_DIR="$(cd "$(dirname "$0")/.."; pwd)"
cd "$ROOT_DIR"

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

start_ts="$(date '+%Y-%m-%d %H:%M:%S')"
echo -e "${YELLOW}[PRE-CHECK] Starting at ${start_ts}${NC}"
echo -e "${YELLOW}[RUN ORDER] 1) test_ssh_system.sh  2) DRY_RUN start-stack-and-health  3) DRY_RUN start-aws-stack${NC}"

echo -e "${YELLOW}[STEP] Validating SSH system...${NC}"
if ! ./scripts/test_ssh_system.sh; then
  echo -e "${RED}[ERROR] SSH system validation failed.${NC}"
  echo -e "${RED} - Ensure all scripts source ssh_key.sh${NC}"
  echo -e "${RED} - Ensure no raw ssh/scp/rsync/.pem/ssh-agent/ssh-add remain${NC}"
  echo -e "${RED} - Ensure scripts are executable (chmod +x)${NC}"
  exit 1
fi

echo -e "${YELLOW}[STEP] DRY_RUN: start-stack-and-health.sh${NC}"
if ! DRY_RUN=1 ./scripts/start-stack-and-health.sh; then
  echo -e "${RED}[ERROR] DRY_RUN failed for start-stack-and-health.sh${NC}"
  exit 1
fi

echo -e "${YELLOW}[STEP] DRY_RUN: start-aws-stack.sh${NC}"
if ! DRY_RUN=1 ./scripts/start-aws-stack.sh 175.41.189.249; then
  echo -e "${RED}[ERROR] DRY_RUN failed for start-aws-stack.sh${NC}"
  exit 1
fi

end_ts="$(date '+%Y-%m-%d %H:%M:%S')"
echo -e "${GREEN}[OK] Pre-deployment check passed. Safe to deploy.${NC}"
echo -e "${GREEN}[PRE-CHECK] Completed at ${end_ts}${NC}"



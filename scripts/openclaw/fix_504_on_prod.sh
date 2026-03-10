#!/usr/bin/env bash
# One-command fix for 504 on https://dashboard.hilovivo.com/openclaw/
# Run this ON the PROD instance (atp-rebuild-2026), e.g. via EC2 Instance Connect or SSH.
#
# What it does:
# - Points Nginx proxy_pass to LAB private IP (default 172.31.3.214:8080 — matches docker-compose.openclaw.yml)
# - Reloads nginx after validating config
#
# Prereqs: repo at /home/ubuntu/automated-trading-platform (or set REPO_ROOT).
# After running: open https://dashboard.hilovivo.com/openclaw/ — expect 401 (Basic Auth), not 504.
#
# If 504 persists: LAB may be down or SG blocking. On LAB run: sudo bash scripts/openclaw/check_and_start_openclaw.sh

set -e
REPO_ROOT="${REPO_ROOT:-/home/ubuntu/automated-trading-platform}"
if [[ ! -d "$REPO_ROOT" ]]; then
  echo "REPO_ROOT not found: $REPO_ROOT. Set REPO_ROOT or run from repo on PROD."
  exit 1
fi
cd "$REPO_ROOT"
export LAB_PRIVATE_IP="${LAB_PRIVATE_IP:-172.31.3.214}"
export OPENCLAW_PORT="${OPENCLAW_PORT:-8080}"
sudo -E bash scripts/openclaw/fix_openclaw_proxy_prod.sh

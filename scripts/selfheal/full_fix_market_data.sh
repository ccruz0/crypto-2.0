#!/usr/bin/env bash
# Runs the same steps as runbook EC2_FIX_MARKET_DATA_NOW (one-shot block), so the
# health alert can fix market_data/market_updater automatically instead of only
# notifying. Invoked when targeted remediation has hit max attempts (optional
# replacement or complement to heal.sh for market incidents).
#
# Does NOT stop/start the self-heal timer (caller is the timer).
# Env: REPO_DIR, ATP_HEALTH_BASE (default http://127.0.0.1:8002), ATP_FULL_FIX_SKIP_VERIFY_RESTORE=1 to skip restoring verify.sh.
set -euo pipefail

REPO_DIR="${REPO_DIR:-$HOME/automated-trading-platform}"
BASE="${ATP_HEALTH_BASE:-http://127.0.0.1:8002}"
SKIP_VERIFY_RESTORE="${ATP_FULL_FIX_SKIP_VERIFY_RESTORE:-0}"

log() { echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] full_fix_market_data $*"; }

cd "$REPO_DIR" || { log "error=repo_missing path=$REPO_DIR"; exit 1; }

# 1) Restore verify.sh if missing or broken (so next snapshot can PASS)
if [ "$SKIP_VERIFY_RESTORE" != "1" ]; then
  if ! bash -n scripts/selfheal/verify.sh 2>/dev/null; then
    log "restore verify.sh (syntax was broken or missing)"
    if [ -f scripts/selfheal/emit_verify_sh.py ]; then
      python3 scripts/selfheal/emit_verify_sh.py 2>/dev/null || true
    fi
    if ! bash -n scripts/selfheal/verify.sh 2>/dev/null && command -v git >/dev/null 2>&1; then
      git fetch origin main 2>/dev/null || true
      git checkout origin/main -- scripts/selfheal/verify.sh 2>/dev/null || true
    fi
    chmod +x scripts/selfheal/verify.sh 2>/dev/null || true
  fi
fi

# 2) Ensure .env and .env.aws
if [ ! -f .env ]; then
  [ -f .env.example ] && cp .env.example .env && log "created .env from .env.example"
fi
if [ ! -f .env.aws ]; then
  [ -f .env ] && cp .env .env.aws && log "created .env.aws from .env"
fi

# 3) Restart Docker and full stack
log "restart docker and stack"
sudo systemctl restart docker 2>/dev/null || true
sleep 5
docker compose --profile aws up -d --remove-orphans
docker compose --profile aws restart || true
sleep 15

# 4) Health fix + update-cache
log "POST health/fix and update-cache"
curl -sS -X POST --max-time 30 "$BASE/api/health/fix" >/dev/null || true
curl -sS -X POST --max-time 90 "$BASE/api/market/update-cache" >/dev/null || true

# 5) Ensure market-updater is up
docker compose --profile aws up -d market-updater-aws
sleep 30

# 6) Second round after updater had time
curl -sS -X POST --max-time 30 "$BASE/api/health/fix" >/dev/null || true
curl -sS -X POST --max-time 60 "$BASE/api/market/update-cache" >/dev/null || true

log "full_fix_market_data finished (run verify.sh to confirm)"

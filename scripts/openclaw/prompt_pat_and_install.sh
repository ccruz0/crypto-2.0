#!/usr/bin/env bash
# Secure OpenClaw LAB install: PAT only on LAB via SSH, never in SSM or logs.
# Usage: ./scripts/openclaw/prompt_pat_and_install.sh
# Requires: SSH access to LAB (set LAB_SSH_HOST, LAB_SSH_KEY; or we resolve from LAB_INSTANCE_ID).
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
LAB_INSTANCE_ID="${LAB_INSTANCE_ID:-i-0d82c172235770a0d}"
REGION="${REGION:-ap-southeast-1}"
LAB_SSH_USER="${LAB_SSH_USER:-ubuntu}"

# Resolve LAB SSH target
if [ -z "${LAB_SSH_HOST-}" ]; then
  LAB_SSH_HOST=$(aws ec2 describe-instances --instance-ids "$LAB_INSTANCE_ID" --region "$REGION" \
    --query 'Reservations[0].Instances[0].PublicIpAddress' --output text 2>/dev/null) || true
fi
if [ -z "${LAB_SSH_HOST-}" ] || [ "$LAB_SSH_HOST" = "None" ]; then
  echo "ERROR: Could not resolve LAB host. Set LAB_SSH_HOST (e.g. LAB_SSH_HOST=1.2.3.4) or ensure LAB_INSTANCE_ID=$LAB_INSTANCE_ID has a public IP." >&2
  exit 1
fi
SSH_KEY_OPTS=()
if [ -n "${LAB_SSH_KEY-}" ] && [ -f "$LAB_SSH_KEY" ]; then
  SSH_KEY_OPTS=(-i "$LAB_SSH_KEY" -o StrictHostKeyChecking=accept-new)
fi
SSH_TARGET="${LAB_SSH_USER}@${LAB_SSH_HOST}"

_run_ssh() {
  if [ ${#SSH_KEY_OPTS[@]} -gt 0 ]; then
    ssh "${SSH_KEY_OPTS[@]}" "$SSH_TARGET" "$@"
  else
    ssh -o StrictHostKeyChecking=accept-new "$SSH_TARGET" "$@"
  fi
}

echo "LAB target: $SSH_TARGET (PAT will never be logged or sent to SSM)"

# --- Phase 4: Egress validation (before touching token) ---
echo "Checking HTTPS egress on LAB..."
if ! _run_ssh "curl -sI --connect-timeout 10 https://github.com" >/dev/null 2>&1; then
  echo "ERROR: LAB instance has no HTTPS egress (port 443). Fix Security Group or NAT before continuing." >&2
  exit 1
fi
if ! _run_ssh "curl -sI --connect-timeout 10 https://api.github.com" >/dev/null 2>&1; then
  echo "ERROR: LAB instance cannot reach api.github.com. Fix egress before continuing." >&2
  exit 1
fi
echo "Egress OK."

# --- Get PAT (pop-up or read -s), never echo ---
if [ -n "${OPENCLAW_PAT-}" ]; then
  :
elif [ -f "$REPO_ROOT/.openclaw_pat" ]; then
  OPENCLAW_PAT=$(cat "$REPO_ROOT/.openclaw_pat")
elif [ -f ~/.openclaw_pat ]; then
  OPENCLAW_PAT=$(cat ~/.openclaw_pat)
else
  if [ "$(uname -s)" = "Darwin" ]; then
    OPENCLAW_PAT=$(osascript -e 'display dialog "Pega tu GitHub fine-grained PAT (Contents R/W, Pull requests R/W):" with title "OpenClaw LAB" default answer "" with hidden answer' -e 'text returned of result' 2>/dev/null) || true
  fi
  if [ -z "${OPENCLAW_PAT-}" ]; then
    echo "GitHub fine-grained PAT (se ocultará al escribir):"
    read -r -s OPENCLAW_PAT
    echo
  fi
fi
if [ -z "${OPENCLAW_PAT-}" ]; then
  echo "No se proporcionó PAT. Usa OPENCLAW_PAT=... o crea .openclaw_pat (gitignored)." >&2
  exit 1
fi

# --- Phase 1: Token only on LAB via SSH (no SSM) ---
# Token via stdin only; no echo subprocess, no args visible in ps. User: LAB_SSH_USER (ubuntu) → file in ~/secrets (same UID 1000 as container).
echo "Creating ~/secrets on LAB and writing token (read-only file)..."
_run_ssh "mkdir -p ~/secrets && chmod 700 ~/secrets"
_run_ssh "cat > ~/secrets/openclaw_token && chmod 600 ~/secrets/openclaw_token && chown ${LAB_SSH_USER}:${LAB_SSH_USER} ~/secrets/openclaw_token" <<< "$OPENCLAW_PAT"
unset OPENCLAW_PAT

# --- Phase 2: Verification on LAB ---
echo "Verifying token file on LAB..."
_run_ssh "ls -la ~/secrets"
_run_ssh "stat ~/secrets/openclaw_token"
if ! _run_ssh "test -f ~/secrets/openclaw_token && test -r ~/secrets/openclaw_token"; then
  echo "ERROR: Token file on LAB is missing or not readable by owner." >&2
  exit 1
fi
echo "Token file OK (mode 600, owner only)."

# --- Optional: run full install on LAB (token step skipped; file already exists) ---
echo "Run full install on LAB now? (clone/repo, .env.lab, docker compose) [y/N]"
read -r -n 1 confirm
echo
if [ "$confirm" = "y" ] || [ "$confirm" = "Y" ]; then
  _run_ssh "cd /home/ubuntu && ([ -d automated-trading-platform/.git ] || git clone https://github.com/ccruz0/crypto-2.0.git automated-trading-platform) && cd automated-trading-platform && git fetch origin main && git checkout main && bash scripts/openclaw/install_on_lab.sh"
else
  echo "Done. SSH to LAB and run: bash scripts/openclaw/install_on_lab.sh (token step will be skipped)."
fi

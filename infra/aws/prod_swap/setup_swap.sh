#!/usr/bin/env bash
# Create and enable a swap file on Ubuntu (e.g. PROD EC2) for memory safety margin.
# Does not modify docker, nginx, backend, timers, or other ATP runtime logic.
#
# Usage: run on PROD (e.g. via SSM) with optional SWAP_SIZE_GB=2 (default 2G)
#   SWAP_SIZE_GB=2 ./setup_swap.sh
#
# Requires: root or sudo

set -euo pipefail

SWAP_FILE="/swapfile"
SWAP_SIZE_GB="${SWAP_SIZE_GB:-2}"
FSTAB_SWAP_ENTRY="/swapfile none swap sw 0 0"

# --- Must run as root (or effective root via sudo) ---
if [ "$(id -u)" -ne 0 ]; then
  echo "ERROR: This script must be run as root (e.g. sudo $0)." >&2
  exit 1
fi

echo "=== PROD swap setup (memory hardening) ==="
echo "Swap file:  $SWAP_FILE"
echo "Size:      ${SWAP_SIZE_GB}G (override with SWAP_SIZE_GB)"
echo ""

# --- Check if swap is already enabled ---
if swapon --show 2>/dev/null | grep -q .; then
  echo "Swap is already enabled. Current state:"
  swapon --show 2>/dev/null
  echo ""
  free -h
  echo ""
  echo "No change made. Exiting safely (0)."
  exit 0
fi

echo "--- Before ---"
free -h
echo ""

# --- Remove existing swap file if present but swap off (idempotent) ---
if [ -f "$SWAP_FILE" ]; then
  echo "Found existing $SWAP_FILE; ensuring swap is off before reusing."
  swapoff "$SWAP_FILE" 2>/dev/null || true
  rm -f "$SWAP_FILE"
fi

# --- Create swap file ---
echo "Creating ${SWAP_SIZE_GB}G swap file at $SWAP_FILE ..."
if ! fallocate -l "${SWAP_SIZE_GB}G" "$SWAP_FILE" 2>/dev/null; then
  echo "fallocate failed, trying dd ..." >&2
  dd if=/dev/zero of="$SWAP_FILE" bs=1M count=$((SWAP_SIZE_GB * 1024)) status=progress
fi

chmod 600 "$SWAP_FILE"
mkswap "$SWAP_FILE"
swapon "$SWAP_FILE"

echo ""
echo "--- After ---"
free -h
echo ""

# --- Persist in /etc/fstab only if not already present ---
if grep -qF "$SWAP_FILE" /etc/fstab 2>/dev/null; then
  echo "fstab already contains an entry for $SWAP_FILE; skipping."
else
  echo "Adding $SWAP_FILE to /etc/fstab for persistence across reboot."
  echo "$FSTAB_SWAP_ENTRY" >> /etc/fstab
fi

echo ""
echo "=== Done ==="
echo "Swap is now active:"
swapon --show 2>/dev/null || true
echo ""
echo "Memory and swap summary:"
free -h
echo ""
echo "No docker, nginx, backend, or ATP timers were modified."

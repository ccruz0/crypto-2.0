#!/usr/bin/env bash
# Run this from your machine (terminal where you have AWS CLI configured).
# Starts OpenClaw on LAB so https://dashboard.hilovivo.com/openclaw/ returns 401 instead of 504.
# Port 22 is open on LAB; this uses EC2 Instance Connect + SSH.
set -e
cd "$(dirname "$0")/../.."
echo "Starting OpenClaw on LAB..."
bash scripts/openclaw/start_openclaw_on_lab_via_eice.sh
echo ""
echo "Then open: https://dashboard.hilovivo.com/openclaw/ (expect 401, then sign in with Basic Auth)"

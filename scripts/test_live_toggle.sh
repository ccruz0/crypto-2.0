#!/usr/bin/env bash
set -euo pipefail

# Automated test for LIVE_TRADING toggle endpoint
# This script will:
# 1) Read current status
# 2) Toggle to the opposite state and verify JSON
# 3) Toggle back to original and verify JSON
#
# Usage:
#   ./scripts/test_live_toggle.sh
# Env:
#   API_URL: base API url (default: https://dashboard.hilovivo.com/api)
#   READ_ONLY=1: only check status, do not toggle
#
# Requirements: jq

API_URL="${API_URL:-https://dashboard.hilovivo.com/api}"
READ_ONLY="${READ_ONLY:-0}"
HDR_CT='Content-Type: application/json'
HDR_KEY='x-api-key: demo-key'

echo "[TEST] Using API_URL=${API_URL}"

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || { echo "❌ Missing required command: $1"; exit 1; }
}
require_cmd curl
require_cmd jq

get_status() {
  curl -sS -m 10 "${API_URL}/trading/live-status" | jq -c .
}

toggle() {
  local enabled="$1"
  curl -sS -m 15 -X POST "${API_URL}/trading/live-toggle" \
    -H "${HDR_CT}" -H "${HDR_KEY}" \
    -d "{\"enabled\": ${enabled}}" | jq -c .
}

echo "[STEP] Fetching current status..."
status_json="$(get_status || true)"
echo "  status: ${status_json}"

if [[ -z "${status_json}" || "${status_json}" == "null" ]]; then
  echo "❌ Empty/invalid status response"
  exit 1
fi

ok_val="$(echo "${status_json}" | jq -r '.ok // .success // empty')"
enabled_val="$(echo "${status_json}" | jq -r '.live_trading_enabled // empty')"
mode_val="$(echo "${status_json}" | jq -r '.mode // empty')"

if [[ -z "${enabled_val}" || -z "${mode_val}" ]]; then
  echo "❌ Missing expected fields in status JSON (live_trading_enabled/mode)"
  exit 1
fi

echo "[INFO] Current enabled=${enabled_val}, mode=${mode_val}"

if [[ "${READ_ONLY}" == "1" ]]; then
  echo "[OK] READ_ONLY=1 - status check complete."
  exit 0
fi

flip_to="true"
if [[ "${enabled_val}" == "true" ]]; then
  flip_to="false"
fi

echo "[STEP] Toggling to ${flip_to}..."
toggle_json="$(toggle "${flip_to}" || true)"
echo "  toggle_resp: ${toggle_json}"

if [[ -z "${toggle_json}" || "${toggle_json}" == "null" ]]; then
  echo "❌ Empty/invalid toggle response"
  exit 1
fi

succ_val="$(echo "${toggle_json}" | jq -r '.success // .ok // empty')"
new_enabled="$(echo "${toggle_json}" | jq -r '.live_trading_enabled // empty')"
new_mode="$(echo "${toggle_json}" | jq -r '.mode // empty')"

if [[ "${succ_val}" != "true" ]]; then
  echo "❌ Toggle failed: $(echo "${toggle_json}" | jq -r '.error // .message // .detail // @json')"
  exit 1
fi

if [[ -z "${new_enabled}" || -z "${new_mode}" ]]; then
  echo "❌ Missing expected fields after toggle"
  exit 1
fi

echo "[VERIFY] Fetching status to confirm new state..."
status_after="$(get_status || true)"
echo "  status_after: ${status_after}"
enabled_after="$(echo "${status_after}" | jq -r '.live_trading_enabled // empty')"

if [[ "${enabled_after}" != "${flip_to}" ]]; then
  echo "❌ Status did not reflect toggled state"
  exit 1
fi

echo "[STEP] Restoring original state (${enabled_val})..."
restore_json="$(toggle "${enabled_val}" || true)"
echo "  restore_resp: ${restore_json}"
succ_restore="$(echo "${restore_json}" | jq -r '.success // .ok // empty')"
if [[ "${succ_restore}" != "true" ]]; then
  echo "❌ Restore toggle failed"
  exit 1
fi

echo "[OK] LIVE_TRADING toggle endpoint passed end-to-end test."



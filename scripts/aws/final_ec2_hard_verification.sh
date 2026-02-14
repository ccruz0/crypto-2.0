#!/usr/bin/env bash
# Final EC2 hard verification (strict mode). Run on EC2 host only.
# Production-safe. No secret leakage. CI-ready.
# Exit 0 only if all phases pass; prints exactly "PHASE 6 — EC2 VALIDATION COMPLETE".
# On any failure: prints exactly "VALIDATION BLOCKED — <step_name>" and exits 1.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
cd "${REPO_ROOT}"

trap 'echo "VALIDATION BLOCKED — UNHANDLED_ERROR"; exit 1' ERR

command -v jq >/dev/null 2>&1 || { echo "VALIDATION BLOCKED — MISSING_JQ"; exit 1; }

block() {
  trap - ERR
  echo "VALIDATION BLOCKED — $1"
  exit 1
}

# PHASE A — Environment Proof (no secrets; hostname/egress/git for audit)
hostname >/dev/null
curl -s --connect-timeout 3 --max-time 15 --retry 0 https://api.ipify.org >/dev/null || true
git rev-parse --short HEAD 2>/dev/null >/dev/null || true

# PHASE B — ACCOUNT_OK (Signed API Hard Check)
B_OUT="$(docker compose --profile aws exec -T backend-aws python3 - << 'PY' 2>&1
try:
    from app.services.brokers.crypto_com_trade import CryptoComTradeClient
    client = CryptoComTradeClient()
    res = client.get_account_summary()
    if isinstance(res, dict) and res.get("code") == 40101:
        print("ACCOUNT_STATUS=FAIL")
    else:
        print("ACCOUNT_STATUS=OK" if isinstance(res, dict) else "ACCOUNT_STATUS=FAIL")
except Exception:
    print("ACCOUNT_STATUS=FAIL")
PY
)" || B_OUT="ACCOUNT_STATUS=FAIL"
if ! echo "$B_OUT" | grep -q "ACCOUNT_STATUS=OK"; then
  block "PHASE B: ACCOUNT_NOT_OK"
fi

# PHASE C — Risk Probe (curl to file, jq, remove temp files)
C1_JSON="$(mktemp)"
C2_JSON="$(mktemp)"
D1_JSON="$(mktemp)"
trap 'rm -f "$C1_JSON" "$C2_JSON" "$D1_JSON"' EXIT

# Spot probe: tiny trade value so it stays under 10% equity cap when exchange returns equity
C1_CODE="$(curl -s --connect-timeout 3 --max-time 15 --retry 0 -o "$C1_JSON" -w "%{http_code}" -X POST http://127.0.0.1:8002/api/risk/probe \
  -H "Content-Type: application/json" \
  -d '{"symbol":"BTC_USDT","side":"BUY","price":1,"quantity":0.0001,"is_margin":false,"trade_on_margin_from_watchlist":false}')"
if [[ "$C1_CODE" != "200" ]]; then
  block "PHASE C.1: Risk probe spot returned HTTP $C1_CODE (expected 200)"
fi
C1_ALLOWED="$(jq -r '.allowed' "$C1_JSON")"
if [[ "$C1_ALLOWED" != "true" ]]; then
  block "PHASE C.1: Risk probe spot allowed is not true"
fi

C2_CODE="$(curl -s --connect-timeout 3 --max-time 15 --retry 0 -o "$C2_JSON" -w "%{http_code}" -X POST http://127.0.0.1:8002/api/risk/probe \
  -H "Content-Type: application/json" \
  -d '{"symbol":"BTC_USDT","side":"BUY","price":50000,"quantity":0.01,"is_margin":true,"leverage":10,"trade_on_margin_from_watchlist":true}')"
if [[ "$C2_CODE" != "400" ]]; then
  block "PHASE C.2: Risk probe margin over-cap returned HTTP $C2_CODE (expected 400)"
fi
C2_ALLOWED="$(jq -r '.allowed' "$C2_JSON")"
C2_REASON="$(jq -r '.reason_code' "$C2_JSON")"
if [[ "$C2_ALLOWED" != "false" ]]; then
  block "PHASE C.2: Risk probe margin over-cap allowed must be false"
fi
if [[ "$C2_REASON" != "RISK_GUARD_BLOCKED" ]]; then
  block "PHASE C.2: Risk probe margin over-cap reason_code must be RISK_GUARD_BLOCKED"
fi

# PHASE D — Health & Integrity (health endpoint can be slow under load; allow 30s)
# Capture curl exit so set -e doesn't fire on connection failure; we block() below with real message
D1_CODE="$(curl -s --connect-timeout 5 --max-time 30 --retry 0 -o "$D1_JSON" -w "%{http_code}" http://127.0.0.1:8002/api/health/system)" || D1_CODE="000"
if [[ "$D1_CODE" != "200" ]]; then
  block "PHASE D.1: System health returned HTTP $D1_CODE (expected 200)"
fi
D1_GS="$(jq -r '.global_status' "$D1_JSON")"
D1_DB="$(jq -r '.db_status' "$D1_JSON")"
D1_OI="$(jq -r '.trade_system.order_intents_table_exists' "$D1_JSON")"
D1_TG="$(jq -r '.telegram.status' "$D1_JSON")"
if [[ "$D1_GS" != "PASS" && "$D1_GS" != "WARN" ]]; then
  block "PHASE D.1: System health global_status must be PASS or WARN"
fi
if [[ "$D1_DB" != "up" ]]; then
  block "PHASE D.1: System health db_status must be up"
fi
if [[ "$D1_OI" != "true" ]]; then
  block "PHASE D.1: System health order_intents_table_exists must be true"
fi
if [[ "$D1_TG" != "PASS" ]]; then
  block "PHASE D.1: System health telegram.status must be PASS"
fi

if ! bash "${REPO_ROOT}/scripts/aws/health_guard.sh" >/dev/null 2>&1; then
  block "PHASE D.2: health_guard.sh did not exit 0"
fi
if ! bash "${REPO_ROOT}/scripts/aws/nightly_integrity_audit.sh" >/dev/null 2>&1; then
  block "PHASE D.3: nightly_integrity_audit.sh did not exit 0"
fi

# PHASE E — Systemd Timer
if [[ "$(sudo systemctl is-enabled nightly-integrity-audit.timer 2>/dev/null)" != "enabled" ]]; then
  block "PHASE E: nightly-integrity-audit.timer is not enabled"
fi
if [[ "$(sudo systemctl is-active nightly-integrity-audit.timer 2>/dev/null)" != "active" ]]; then
  block "PHASE E: nightly-integrity-audit.timer is not active"
fi
if ! sudo systemctl list-timers --all 2>/dev/null | grep -qi nightly-integrity-audit; then
  block "PHASE E: nightly-integrity-audit.timer not in list-timers"
fi
JOURNAL="$(sudo journalctl -u nightly-integrity-audit.service -n 50 --no-pager 2>/dev/null)"
if [[ $(echo "$JOURNAL" | wc -l) -lt 1 ]]; then
  block "PHASE E: Could not read journal for nightly-integrity-audit.service"
fi
if ! echo "$JOURNAL" | grep -q "PASS"; then
  block "PHASE E: nightly-integrity-audit.service journal did not show PASS"
fi

# PHASE F — Port Hardening
PORT_OUT="$(ss -ltnp 2>/dev/null | grep -E "(:8002|:3000)" || true)"
if ! echo "$PORT_OUT" | grep -q "127.0.0.1:8002"; then
  block "PHASE F: 127.0.0.1:8002 not found"
fi
if ! echo "$PORT_OUT" | grep -q "127.0.0.1:3000"; then
  block "PHASE F: 127.0.0.1:3000 not found"
fi
if echo "$PORT_OUT" | grep -E "(:8002|:3000)" | grep -q "0.0.0.0"; then
  block "PHASE F: Ports 8002 or 3000 must not bind to 0.0.0.0"
fi

echo "PHASE 6 — EC2 VALIDATION COMPLETE"
exit 0

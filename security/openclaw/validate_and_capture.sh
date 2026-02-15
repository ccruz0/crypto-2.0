#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/../.."

OUT_DIR="docs/openclaw"
mkdir -p "$OUT_DIR"

TS="$(date +%Y%m%d_%H%M%S)"
OUT_FILE="$OUT_DIR/OPENCLAW_EVIDENCE_${TS}.txt"

{
  echo "== OpenClaw Level-2 Evidence =="
  echo "timestamp: $TS"
  echo

  echo "== docker compose ps =="
  docker compose -f security/openclaw/docker-compose.openclaw.yml ps
  echo

  echo "== OpenAI connectivity test (masked) =="
  docker compose -f security/openclaw/docker-compose.openclaw.yml run --rm openclaw-agent bash -c '
python - << "PY"
import os, urllib.request

path = os.getenv("OPENAI_API_KEY_FILE", "/run/secrets/openai_api_key")
key = open(path, "r", encoding="utf-8").read().strip()
masked = (key[:4] + "..." + key[-4:]) if len(key) > 8 else "INVALID"
print("Key (masked):", masked)

req = urllib.request.Request(
  "https://api.openai.com/v1/models",
  headers={"Authorization": f"Bearer {key}"}
)
try:
  with urllib.request.urlopen(req, timeout=15) as r:
    print("OpenAI status:", r.status)
except Exception as e:
  print("OpenAI call failed:", type(e).__name__)
PY
'
} | tee "$OUT_FILE"

echo
echo "Evidence saved to: $OUT_FILE"

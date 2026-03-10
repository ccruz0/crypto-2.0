#!/usr/bin/env bash
# Ensure OpenClaw gateway auth token is persistent on LAB.
# Run on the LAB host:
#   cd /home/ubuntu/automated-trading-platform
#   sudo bash scripts/openclaw/ensure_openclaw_gateway_token.sh
#
# Optional:
#   OPENCLAW_CONFIG_PATH=/opt/openclaw/openclaw.json   # default
#   ROTATE=1                                            # force new token
#
# Behavior:
# - Keeps existing gateway.auth.token by default.
# - Creates config and token if missing.
# - Restarts container only when token changes.
set -euo pipefail

OPENCLAW_CONFIG_PATH="${OPENCLAW_CONFIG_PATH:-/opt/openclaw/openclaw.json}"
ROTATE="${ROTATE:-0}"
TMP_OUT="$(mktemp)"

python3 - "$OPENCLAW_CONFIG_PATH" "$ROTATE" "$TMP_OUT" <<'PY'
import json
import pathlib
import secrets
import sys

config_path = pathlib.Path(sys.argv[1])
rotate = sys.argv[2] == "1"
out_path = pathlib.Path(sys.argv[3])

config_path.parent.mkdir(parents=True, exist_ok=True)

cfg = {}
if config_path.exists():
    try:
        cfg = json.loads(config_path.read_text(encoding="utf-8") or "{}")
    except Exception:
        cfg = {}

gateway = cfg.setdefault("gateway", {})
auth = gateway.setdefault("auth", {})

old_token = str(auth.get("token") or "").strip()
new_token = secrets.token_hex(24) if rotate or not old_token else old_token
auth["token"] = new_token

tmp_path = config_path.with_suffix(config_path.suffix + ".tmp")
tmp_path.write_text(json.dumps(cfg, separators=(",", ":")), encoding="utf-8")
tmp_path.replace(config_path)

out_path.write_text(
    "\n".join(
        [
            f"old_token={old_token}",
            f"new_token={new_token}",
            f"changed={'1' if new_token != old_token else '0'}",
        ]
    ),
    encoding="utf-8",
)
PY

OLD_TOKEN="$(sed -n 's/^old_token=//p' "$TMP_OUT")"
NEW_TOKEN="$(sed -n 's/^new_token=//p' "$TMP_OUT")"
CHANGED="$(sed -n 's/^changed=//p' "$TMP_OUT")"
rm -f "$TMP_OUT"

chmod 600 "$OPENCLAW_CONFIG_PATH" 2>/dev/null || true

echo "OpenClaw config: $OPENCLAW_CONFIG_PATH"
if [[ "$CHANGED" == "1" ]]; then
  echo "Gateway token updated."
  if command -v docker >/dev/null 2>&1 && docker ps --format '{{.Names}}' | grep -qx openclaw; then
    docker restart openclaw >/dev/null
    echo "Container restarted: openclaw"
  else
    echo "Container openclaw not running; restart it manually after setting token."
  fi
else
  echo "Gateway token unchanged (persistent token already configured)."
fi

echo ""
echo "Gateway token (save securely and paste once in Control UI settings):"
echo "$NEW_TOKEN"

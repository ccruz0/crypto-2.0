#!/usr/bin/env bash
# Phase C remote payload — runs ON prod via SSM. Do not run locally.
# Strips static AWS keys from env files, recreates backend-aws (pinned image),
# verifies health / signal monitor / advisory lock, then canary + market-updater.
# Never prints secret values.
set -euo pipefail

echo "=== Phase C remote: strip static AWS keys, recreate backend-aws ==="

if [ -d /home/ubuntu/crypto-2.0/.git ]; then
  cd /home/ubuntu/crypto-2.0
elif [ -d /home/ubuntu/automated-trading-platform/.git ]; then
  cd /home/ubuntu/automated-trading-platform
else
  echo "FAIL: no production git repository found" >&2
  exit 1
fi
echo "repo=$(pwd)"

STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
NOTE="secrets/runtime.env.strip-note-${STAMP}.txt"
CLEAN_BACKUP="secrets/runtime.env.stripped-${STAMP}"
DC=(docker compose --profile aws -f docker-compose.yml)

python3 - "$STAMP" "$NOTE" "$CLEAN_BACKUP" <<'PY'
import os
import sys
from pathlib import Path

stamp, note_path, backup_path = sys.argv[1], sys.argv[2], sys.argv[3]
drop = {"AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN"}
files = ["secrets/runtime.env", ".env", ".env.aws"]
report = [f"stamp={stamp}", "action=removed_static_aws_key_lines", "values_not_stored"]

for rel in files:
    path = Path(rel)
    if not path.is_file():
        report.append(f"{rel}: absent")
        continue
    text = path.read_text(encoding="utf-8")
    out_lines = []
    removed = []
    for line in text.splitlines(True):
        stripped = line.lstrip()
        if not stripped or stripped.startswith("#") or "=" not in line:
            out_lines.append(line)
            continue
        key = line.split("=", 1)[0].strip()
        if key in drop:
            removed.append(key)
            continue
        out_lines.append(line)
    path.write_text("".join(out_lines), encoding="utf-8")
    os.chmod(path, 0o640)
    report.append(f"{rel}: removed={','.join(removed) if removed else 'none'}")

Path(backup_path).write_text(Path("secrets/runtime.env").read_text(encoding="utf-8"), encoding="utf-8")
os.chmod(backup_path, 0o640)
report.append(f"cleaned_backup={backup_path} (no secret values)")
Path(note_path).write_text("\n".join(report) + "\n", encoding="utf-8")
print("\n".join(report))
PY

echo "compose AWS_* key names in docker-compose.yml (expect none):"
grep -E 'AWS_ACCESS_KEY_ID|AWS_SECRET_ACCESS_KEY|AWS_SESSION_TOKEN' docker-compose.yml && echo "FAIL: compose still injects AWS keys" >&2 && exit 1 || echo "compose: no AWS key env vars"

CID="$("${DC[@]}" ps -q backend-aws 2>/dev/null || true)"
if [[ -z "$CID" ]]; then
  echo "FAIL: backend-aws is not running — refusing recreate" >&2
  exit 1
fi
RUNNING_IMAGE="$(docker inspect --format='{{.Config.Image}}' "$CID")"
if [[ -z "$RUNNING_IMAGE" ]] || printf '%s' "$RUNNING_IMAGE" | grep -qE ':latest$'; then
  echo "FAIL: could not pin backend image (got '${RUNNING_IMAGE:-empty}'). Refusing :latest revert." >&2
  exit 1
fi
echo "pinned_image=$RUNNING_IMAGE"

echo "=== Recreate backend-aws only (env_file reload requires recreate, not restart) ==="
BACKEND_IMAGE="$RUNNING_IMAGE" "${DC[@]}" up -d --force-recreate --no-deps backend-aws

echo "=== Wait for /api/health/ready ==="
READY=0
for i in $(seq 1 40); do
  if curl -sf --connect-timeout 3 --max-time 8 "http://127.0.0.1:8002/api/health/ready" >/dev/null; then
    echo "ready after ${i} attempts"
    READY=1
    break
  fi
  sleep 6
done
if [[ "$READY" -ne 1 ]]; then
  echo "FAIL: /api/health/ready did not return 200. STOP. Do not recreate other services." >&2
  "${DC[@]}" logs --tail=80 backend-aws || true
  exit 1
fi

echo "=== Wait for signal monitor + advisory lock ==="
SM_OK=0
for i in $(seq 1 20); do
  SYS="$(curl -sf --connect-timeout 3 --max-time 10 "http://127.0.0.1:8002/api/health/system" || true)"
  EVAL="$(python3 -c '
import json,sys
raw=sys.stdin.read().strip()
if not raw:
    print("FAIL empty_health"); raise SystemExit(0)
h=json.loads(raw)
sm=h.get("signal_monitor") or {}
running=bool(sm.get("is_running"))
status=str(sm.get("status") or "")
pid=sm.get("last_lock_backend_pid")
rl=sm.get("run_locked_count")
print(f"signal_status={status} is_running={running} last_lock_backend_pid={pid} run_locked_count={rl}")
if running and status != "FAIL":
    print("SIGNAL_OK")
' <<<"$SYS" 2>/dev/null || echo "FAIL parse")"
  echo "attempt=$i $EVAL"
  if echo "$EVAL" | grep -q SIGNAL_OK; then
    SM_OK=1
    break
  fi
  sleep 9
done
if [[ "$SM_OK" -ne 1 ]]; then
  echo "FAIL: signal monitor / advisory lock not healthy. STOP." >&2
  echo "$SYS" | python3 -c 'import json,sys; h=json.loads(sys.stdin.read()); print({k:h.get(k) for k in ("global_status","signal_monitor")})' 2>/dev/null || true
  "${DC[@]}" logs --tail=80 backend-aws || true
  exit 1
fi

echo "=== Container must not have static AWS keys ==="
"${DC[@]}" exec -T backend-aws python -c '
import os
bad = False
for k in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN"):
    v = os.getenv(k)
    present = bool(v is not None and str(v).strip() != "")
    print("%s_SET=%s" % (k, "yes" if present else "no"))
    if present:
        bad = True
if bad:
    raise SystemExit("static AWS key still in container env")
'

echo "=== STS caller (must be assumed-role/atp-backend-ec2-role) ==="
ARN="$("${DC[@]}" exec -T backend-aws python -c 'import boto3; print(boto3.client("sts").get_caller_identity()["Arn"])')"
echo "sts_arn=$ARN"
if ! echo "$ARN" | grep -q 'assumed-role/atp-backend-ec2-role'; then
  echo "FAIL: caller is not atp-backend-ec2-role (check IMDS hop limit 2 / empty AWS_ACCESS_KEY_ID)." >&2
  exit 1
fi

echo "=== Credential errors in backend-aws logs (Bedrock Operation not allowed is expected) ==="
"${DC[@]}" logs --tail=120 backend-aws 2>&1 | grep -iE 'InvalidClientTokenId|UnrecognizedClientException|Unable to locate credentials|ExpiredToken|InvalidAccessKeyId' && echo "WARN: credential errors in logs" || echo "no static-key credential errors in last 120 log lines"
"${DC[@]}" logs --tail=120 backend-aws 2>&1 | grep -iE 'Operation not allowed|AccessDeniedException' | head -5 || true

echo "=== Recreate backend-aws-canary (same pinned image) ==="
CANARY_CID="$("${DC[@]}" ps -q backend-aws-canary 2>/dev/null || true)"
if [[ -n "$CANARY_CID" ]]; then
  BACKEND_IMAGE="$RUNNING_IMAGE" "${DC[@]}" up -d --force-recreate --no-deps backend-aws-canary
  for i in $(seq 1 20); do
    if curl -sf --connect-timeout 2 --max-time 5 "http://127.0.0.1:8003/api/health/ready" >/dev/null; then
      echo "canary ready"
      break
    fi
    sleep 6
  done
else
  echo "canary not running; skip (will not start a stopped canary)"
fi

echo "=== Recreate market-updater-aws (same pinned image) ==="
if "${DC[@]}" ps -q market-updater-aws >/dev/null 2>&1 && [[ -n "$("${DC[@]}" ps -q market-updater-aws 2>/dev/null || true)" ]]; then
  BACKEND_IMAGE="$RUNNING_IMAGE" "${DC[@]}" up -d --force-recreate --no-deps market-updater-aws
  echo "market-updater-aws recreated"
else
  echo "market-updater-aws not running; skip"
fi

echo "=== Re-check primary backend after subsequent recreates ==="
curl -sf --connect-timeout 3 --max-time 8 "http://127.0.0.1:8002/api/health/ready" >/dev/null
echo "primary still ready"
echo "PASS: Phase C remote complete. Jarvis Bedrock may still fail until AWS lifts account restriction."

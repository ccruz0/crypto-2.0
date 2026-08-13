#!/usr/bin/env bash
# Strip static AWS keys from LAB env files. Does not touch PROD.
# Recreates backend-lab only if that container is running.
set -euo pipefail

echo "=== LAB host $(hostname) strip AWS keys ==="
TOKEN=$(curl -sS -m 3 -X PUT "http://169.254.169.254/latest/api/token" -H "X-aws-ec2-metadata-token-ttl-seconds: 60" || true)
IID=$(curl -sS -m 3 -H "X-aws-ec2-metadata-token: $TOKEN" "http://169.254.169.254/latest/meta-data/instance-id" || true)
if echo "$IID" | grep -q 'i-087953603011543c5'; then
  echo "FAIL: this is PROD. Refusing to run LAB switch on atp-rebuild-2026." >&2
  exit 1
fi

python3 - <<'PY'
from pathlib import Path

drop_prefixes = ("AWS_ACCESS_KEY_ID=", "AWS_SECRET_ACCESS_KEY=", "AWS_SESSION_TOKEN=")
candidates = [
    Path("/home/ubuntu/crypto-2.0/secrets/runtime.env.lab"),
    Path("/home/ubuntu/crypto-2.0/secrets/runtime.env"),
    Path("/home/ubuntu/crypto-2.0/.env.lab"),
    Path("/home/ubuntu/crypto-2.0/.env"),
    Path("/home/ubuntu/automated-trading-platform/secrets/runtime.env.lab"),
    Path("/home/ubuntu/automated-trading-platform/secrets/runtime.env"),
]
for path in candidates:
    if not path.is_file():
        print(f"absent {path}")
        continue
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines(True)
    kept = [ln for ln in lines if not ln.startswith(drop_prefixes)]
    removed = len(lines) - len(kept)
    if removed:
        path.write_text("".join(kept), encoding="utf-8")
        print(f"stripped {removed} AWS key line(s) from {path}")
    else:
        print(f"no AWS key lines in {path}")
PY

echo "=== AWS_DEFAULT_REGION (region only) ==="
for f in /home/ubuntu/crypto-2.0/secrets/runtime.env.lab \
         /home/ubuntu/crypto-2.0/secrets/runtime.env; do
  if [[ -f "$f" ]] && ! grep -q '^AWS_DEFAULT_REGION=' "$f"; then
    echo "AWS_DEFAULT_REGION=ap-southeast-1" >> "$f"
    echo "appended AWS_DEFAULT_REGION to $f"
  fi
done

echo "=== Recreate backend-lab if present (not OpenClaw, not prod backend-aws) ==="
if command -v docker >/dev/null 2>&1 && docker ps -a --format '{{.Names}}' | grep -qx 'automated-trading-platform-backend-lab'; then
  COMPOSE_DIR=/home/ubuntu/crypto-2.0
  [[ -d "$COMPOSE_DIR" ]] || COMPOSE_DIR=/home/ubuntu/automated-trading-platform
  cd "$COMPOSE_DIR"
  docker compose -f docker-compose.yml -f docker-compose.lab.yml --profile lab up -d --no-deps --force-recreate backend-lab
  echo "backend-lab recreated"
else
  echo "backend-lab not on this host — skip compose (OpenClaw-only LAB is OK)"
fi

echo "=== Caller identity (host default chain) ==="
aws sts get-caller-identity --query Arn --output text || echo "WARN: aws cli/host identity failed"

if command -v docker >/dev/null 2>&1 && docker ps --format '{{.Names}}' | grep -qx 'automated-trading-platform-backend-lab'; then
  echo "=== Caller identity (backend-lab container) ==="
  docker exec automated-trading-platform-backend-lab python3 -c \
    "import boto3; print(boto3.client('sts').get_caller_identity()['Arn'])"
fi

echo "PASS: LAB static AWS key lines stripped."

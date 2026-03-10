#!/usr/bin/env bash
# Generate a secret and write it to /opt/atp/atp.env on EC2. No value in args or logs.
# Usage: ATP_EC2_HOST=ubuntu@<IP> [ATP_EC2_SSH_KEY=path] ./ops/push_secret_to_ec2.sh <SECRET_NAME>
# Example: ATP_EC2_HOST=ubuntu@1.2.3.4 ./ops/push_secret_to_ec2.sh DIAGNOSTICS_API_KEY
set -euo pipefail

SECRET_NAME="${1:?Usage: push_secret_to_ec2.sh SECRET_NAME}"
HOST="${ATP_EC2_HOST:?Set ATP_EC2_HOST=ubuntu@<IP>}"
KEY="${ATP_EC2_SSH_KEY:-${SSH_KEY:-$HOME/.ssh/id_rsa}}"
TMP="$(mktemp)"
trap 'rm -f "$TMP"' EXIT

case "$SECRET_NAME" in
  DIAGNOSTICS_API_KEY|ADMIN_ACTIONS_KEY)
    VAL="$(openssl rand -hex 32)"
    ;;
  SECRET_KEY)
    VAL="$(python3 -c "import secrets; print(secrets.token_urlsafe(32))")"
    ;;
  POSTGRES_PASSWORD|GF_SECURITY_ADMIN_PASSWORD)
    VAL="$(openssl rand -hex 32)"
    ;;
  *)
    echo "Unknown secret: $SECRET_NAME" >&2
    exit 1
    ;;
esac

echo "${SECRET_NAME}=${VAL}" > "$TMP"
chmod 600 "$TMP"
# Remove existing line on EC2, then append new one
ssh -i "$KEY" -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null "$HOST" \
  "sudo mkdir -p /opt/atp && sudo touch /opt/atp/atp.env && sudo chown ubuntu:ubuntu /opt/atp /opt/atp/atp.env"
scp -i "$KEY" -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null "$TMP" "$HOST:/tmp/atp_append.env"
ssh -i "$KEY" -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null "$HOST" \
  "sed -i '/^${SECRET_NAME}=/d' /opt/atp/atp.env 2>/dev/null || true; cat /tmp/atp_append.env >> /opt/atp/atp.env && rm /tmp/atp_append.env && chmod 600 /opt/atp/atp.env"
echo "OK: $SECRET_NAME written to /opt/atp/atp.env on EC2 (value not echoed)"

#!/usr/bin/env bash
# OpenClaw startup check: verify runtime user can run docker without sudo.
# Used by openclaw.service ExecStartPre. Exit 0 if OK, 1 with clear message if not.
# Requires: runtime user (ubuntu) in docker group. Fix: sudo usermod -aG docker ubuntu
set -euo pipefail

if ! docker ps >/dev/null 2>&1; then
  echo "OpenClaw tools cannot access Docker. Add runtime user to docker group:" >&2
  echo "  sudo usermod -aG docker ubuntu" >&2
  echo "  sudo systemctl restart openclaw" >&2
  exit 1
fi
exit 0

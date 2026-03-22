#!/usr/bin/env bash
# Deprecated: use ./deploy_frontend_ssm.sh (git ref repair, submodule, container reset, poll).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
echo "deploy_frontend_via_ssm.sh is deprecated — forwarding to deploy_frontend_ssm.sh" >&2
exec "$ROOT/deploy_frontend_ssm.sh" "$@"

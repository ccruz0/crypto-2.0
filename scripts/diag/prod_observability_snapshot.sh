#!/usr/bin/env bash
# PROD observability snapshot — read-only diagnostic only.
# Prints a compact snapshot of memory, swap, disk, docker, nginx, SSM, and health endpoints.
# Does NOT restart, heal, modify state, or send alerts.
# Usage: run on PROD (e.g. via SSM or SSH), optionally: ./prod_observability_snapshot.sh

set -euo pipefail

echo "=== PROD Observability Snapshot (read-only) ==="
echo "date:    $(date -Iseconds 2>/dev/null || date)"
echo "hostname: $(hostname 2>/dev/null || echo 'n/a')"
echo "uptime:  $(uptime 2>/dev/null || echo 'n/a')"
echo ""

section() { echo "--- $1 ---"; }

section "free -h"
free -h 2>/dev/null || echo "(free failed)"

section "swapon --show"
swapon --show 2>/dev/null || echo "(swapon failed)"

section "df -h /"
df -h / 2>/dev/null || echo "(df failed)"

section "docker"
systemctl is-active docker 2>/dev/null || echo "(systemctl docker failed)"
section "nginx"
systemctl is-active nginx 2>/dev/null || echo "(systemctl nginx failed)"
section "SSM (snap)"
systemctl is-active snap.amazon-ssm-agent.amazon-ssm-agent 2>/dev/null || echo "(systemctl SSM failed)"

section "docker ps"
docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}" 2>/dev/null || echo "(docker ps failed)"

section "GET /api/health"
curl -sS -m 5 http://127.0.0.1:8002/api/health 2>/dev/null || echo "(curl health failed)"

section "GET /api/health/system"
curl -sS -m 10 http://127.0.0.1:8002/api/health/system 2>/dev/null | head -c 2000
echo ""
# (curl exit not checked; head may succeed even if curl failed)

echo ""
echo "=== end snapshot (no actions taken) ==="

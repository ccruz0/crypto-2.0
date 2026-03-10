#!/usr/bin/env bash
# Print the 3 runbook 504 commands for manual paste (Option B when SSM is ConnectionLost).
# Connect to Dashboard (52.220.32.147) via EC2 Instance Connect or SSH, then paste each block.
# See: docs/openclaw/OPENCLAW_504_UPSTREAM_DIAGNOSIS.md

echo "=============================================="
echo "504 runbook — 3 commands (paste in order)"
echo "Connect: EC2 → atp-rebuild-2026 → Connect → EC2 Instance Connect"
echo "=============================================="
echo ""
echo "--- 1) On Dashboard (52.220.32.147) — Nginx proxy_pass ---"
echo ""
cat << 'CMD1'
sudo nginx -T 2>/dev/null \
| sed -n '/server_name dashboard.hilovivo.com/,/^}/p' \
| sed -n '/location \^~ \/openclaw\//,/}/p'
CMD1
echo ""
echo "   → Anota la IP de proxy_pass http://<IP>:8080/"
echo ""
echo "--- 2) On Dashboard — curl to upstream (sustituye UPSTREAM_IP) ---"
echo ""
echo 'curl -sv --max-time 3 http://UPSTREAM_IP:8080/'
echo ""
echo "--- 3) On OpenClaw host (LAB: Session Manager o la instancia donde corre OpenClaw) ---"
echo ""
cat << 'CMD3'
sudo ss -lntp | grep ':8080' || true
CMD3
echo ""
echo "=============================================="
echo "Pega las 3 salidas y con eso se indica el único cambio."
echo "=============================================="

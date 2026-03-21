#!/usr/bin/env bash
# Run on the DASHBOARD host (nginx for dashboard.hilovivo.com).
# Shows active proxy_pass targets and whether TCP/HTTP to OpenClaw upstream works.
#
# Usage: cd /home/ubuntu/automated-trading-platform && ./scripts/openclaw/diagnose_openclaw_prod.sh
set -u

echo "=========================================="
echo "1) This host (dashboard)"
echo "=========================================="
hostname -f 2>/dev/null || hostname
curl -sS --max-time 2 http://169.254.169.254/latest/meta-data/local-ipv4 2>/dev/null || ip -4 addr show | grep -oP '(?<=inet\s)\d+(\.\d+){3}' | head -3

echo ""
echo "=========================================="
echo "2) Active nginx: proxy_pass for OpenClaw (from nginx -T)"
echo "=========================================="
if command -v nginx >/dev/null 2>&1; then
  echo "--- proxy_pass lines mentioning openclaw paths or 8080/8081 / LAB IP ---"
  sudo nginx -T 2>/dev/null | grep -n 'proxy_pass http://' | grep -E 'openclaw|/ws;|8080|8081|172\.31' || true
else
  echo "nginx not in PATH"
fi

echo ""
echo "=========================================="
echo "3) TCP reachability (from this host to common OpenClaw upstreams)"
echo "=========================================="
for url in \
  "http://127.0.0.1:8080/" \
  "http://127.0.0.1:8081/" \
  "http://172.31.3.214:8080/" \
  "http://172.31.3.214:8081/"
do
  code=$(curl -sS -o /dev/null -w "%{http_code}" --connect-timeout 3 --max-time 5 -I "$url" 2>/dev/null || echo "ERR")
  echo "curl -I $url  ->  HTTP $code"
done

echo ""
echo "=========================================="
echo "4) Public /openclaw/ (no auth — expect 401 if auth OK, 502/503 if broken)"
echo "=========================================="
curl -sS -I --max-time 10 "https://dashboard.hilovivo.com/openclaw/" 2>&1 | head -15 || true

echo ""
echo "=========================================="
echo "5) nginx error.log (last 40 lines, upstream errors)"
echo "=========================================="
sudo grep -E 'openclaw|upstream|connect\\(\\) failed|timed out' /var/log/nginx/error.log 2>/dev/null | tail -40 || sudo tail -40 /var/log/nginx/error.log 2>/dev/null

echo ""
echo "=========================================="
echo "NEXT STEPS"
echo "=========================================="
echo "• If 172.31.* curl shows ERR/000: SG may block this host → LAB, or wrong LAB IP, or OpenClaw down."
echo "• If only 127.0.0.1:8080 works: set nginx proxy_pass to http://127.0.0.1:8080/ (see nginx/dashboard.conf), then deploy:"
echo "    ./scripts/openclaw/deploy_openclaw_basepath_nginx.sh"
echo "• If LAB uses 8080 but nginx points to 8081: run (adjust LAB IP):"
echo "    LAB_PRIVATE_IP=172.31.3.214 OPENCLAW_PORT=8080 sudo bash scripts/openclaw/force_openclaw_proxy_8080_on_prod.sh"
echo "• Repo canonical config: nginx/dashboard.conf — edit all three openclaw proxy_pass lines consistently."

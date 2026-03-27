#!/usr/bin/env bash
# Run on the DASHBOARD host (nginx for dashboard.hilovivo.com).
# Shows active proxy_pass targets and whether TCP/HTTP to OpenClaw upstream works.
#
# Usage: cd /home/ubuntu/crypto-2.0 && ./scripts/openclaw/diagnose_openclaw_prod.sh
set -u

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"

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
echo "3) ATP on THIS host (dashboard nginx expects these — if all fail, compose is down)"
echo "=========================================="
for url in "http://127.0.0.1:3000/" "http://127.0.0.1:8002/ping_fast"; do
  code=$(curl -sS -o /dev/null -w "%{http_code}" --connect-timeout 2 --max-time 4 -I "$url" 2>/dev/null || echo "ERR")
  echo "curl -I $url  ->  HTTP $code"
done
echo "(3000 = frontend-aws, 8002 = backend-aws per nginx/dashboard.conf)"

echo ""
echo "=========================================="
echo "4) OpenClaw upstreams (LAB or local — must match proxy_pass)"
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
echo "5) Public /openclaw/ (no auth — expect 401 if auth OK, 502/503 if broken)"
echo "=========================================="
curl -sS -I --max-time 10 "https://dashboard.hilovivo.com/openclaw/" 2>&1 | head -15 || true

echo ""
echo "=========================================="
echo "6) nginx error.log (last 40 lines, upstream errors)"
echo "=========================================="
sudo grep -E 'openclaw|upstream|connect\\(\\) failed|timed out' /var/log/nginx/error.log 2>/dev/null | tail -40 || sudo tail -40 /var/log/nginx/error.log 2>/dev/null

echo ""
echo "=========================================="
echo "7) Docker ATP profile (if installed in default path)"
echo "=========================================="
if command -v docker >/dev/null 2>&1; then
  (cd "$REPO_ROOT" && docker compose --profile aws ps 2>/dev/null | head -30) || docker ps --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}' 2>/dev/null | head -20 || true
else
  echo "docker not in PATH"
fi

echo ""
echo "=========================================="
echo "NEXT STEPS"
echo "=========================================="
echo "• 172.31.* / 10.* upstream checks (section 4) must be run ON a host inside the VPC (e.g. this dashboard)."
echo "    From a laptop, curl to 172.31.x.x will time out — that is normal (private IP, not internet-routable)."
echo "• If section 3) shows ERR for 3000 and 8002: nginx is up but ATP containers are DOWN on this host."
echo "    cd /home/ubuntu/crypto-2.0 && docker compose --profile aws up -d"
echo "    Then: ss -lntp | grep -E ':3000|:8002'"
echo "• If section 4) all ERR: wrong LAB IP, OpenClaw not running on LAB, or SG blocks dashboard→LAB (TCP 8080/8081)."
echo "    Find LAB private IP in EC2; ensure OpenClaw listens; open SG from this dashboard host's private IP/32 or VPC CIDR."
echo "• If only 127.0.0.1:8080 answers HTTP: on aws compose profile, 8080 is often cAdvisor — verify (docker ps) before using it as OpenClaw."
echo "    If it really is OpenClaw, set all openclaw proxy_pass to http://127.0.0.1:8080/ in nginx/dashboard.conf, then deploy."
echo "• LAB on 8080 but nginx uses 8081: LAB_PRIVATE_IP=x.x.x.x OPENCLAW_PORT=8080 sudo bash scripts/openclaw/force_openclaw_proxy_8080_on_prod.sh"

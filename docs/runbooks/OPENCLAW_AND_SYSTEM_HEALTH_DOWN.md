# OpenClaw not opening + System Health FAIL

**When you see:** Dashboard shows **System Health: FAIL** (Market, Updater, Monitor, Telegram red) and the **OpenClaw** tab is blank.

---

## 1) Diagnose from your machine (no SSH)

Run:

```bash
cd /path/to/automated-trading-platform
./scripts/openclaw/run_openclaw_diagnosis_local.sh
```

- **404** on `/openclaw/` → Nginx block missing. On PROD run:  
  `sudo bash scripts/openclaw/insert_nginx_openclaw_block.sh <LAB_PRIVATE_IP>` then `sudo nginx -t && sudo systemctl reload nginx`.
- **504/502** → OpenClaw upstream unreachable. Ensure LAB is running OpenClaw and PROD nginx upstream points to LAB.
- **401/200** → Proxy OK; OpenClaw may just need auth in a new tab (see §3).

---

## 2) Fix System Health (Market, Updater, Monitor, Telegram)

Health comes from `GET /api/health/system`. **Trade = OK** means the backend and DB are up; the other components are failing.

| Component  | Usual cause | What to do |
|------------|-------------|------------|
| **Market** | No fresh market data | Start/restart market updater; run update-cache. |
| **Updater** | Market data stale → treated as “updater not running” | Same as Market. |
| **Monitor** | Signal monitor not running or no recent cycle | Restart backend so signal_monitor runs; wait 1–2 min for a cycle. |
| **Telegram** | `RUN_TELEGRAM` false, or credentials/kill switch | Set `RUN_TELEGRAM=true`, ensure `TELEGRAM_BOT_TOKEN_*` and `TELEGRAM_CHAT_ID_*` (or AWS equivalents) and kill switch allow delivery. |

**On the server (EC2/SSM or SSH):**

```bash
# Backend reachable?
curl -sS --max-time 5 http://127.0.0.1:8002/api/health/system | jq '.global_status, .market_data.status, .market_updater.status, .signal_monitor.status, .telegram.status'

# If backend is down: restart stack (from repo root)
docker compose --profile aws up -d backend-aws

# Market/Updater: ensure market-updater is running and has run
docker ps -a --format "table {{.Names}}\t{{.Status}}" | grep -E "market|NAMES"
docker logs --tail 100 automated-trading-platform-market-updater-aws-1 2>&1
# Then trigger cache update (see EC2_FIX_MARKET_DATA_NOW.md)
```

Full procedure for market + updater: **[EC2_FIX_MARKET_DATA_NOW.md](EC2_FIX_MARKET_DATA_NOW.md)**.  
For health alert streak (e.g. Telegram alert): **[ATP_HEALTH_ALERT_STREAK_FAIL.md](ATP_HEALTH_ALERT_STREAK_FAIL.md)**.

---

## 3) Fix OpenClaw tab blank

The tab embeds an **iframe** with `src="/openclaw/"`. If that URL returns 404/504 or a 401 without proper headers, the iframe stays blank.

**Quick fix (most cases):**

1. Open **https://dashboard.hilovivo.com/openclaw/** in a **new tab**.
2. Sign in with **Basic Auth** when prompted.
3. Return to the dashboard and **reload** the page. The iframe often loads after the session has auth.

If it’s still blank:

- Run the script in §1 and fix 404/504 as indicated.
- See **[OPENCLAW_IFRAME_BLANK_DIAGNOSIS.md](../openclaw/OPENCLAW_IFRAME_BLANK_DIAGNOSIS.md)** for 401/CSP/X-Frame-Options and Nginx `add_header ... always`.

---

## Summary

| Symptom | Action |
|--------|--------|
| System Health FAIL (Market, Updater, Monitor, Telegram) | §2: restart backend, market-updater; check Telegram env and runbooks. |
| OpenClaw tab blank | §1 + §3: run diagnosis script; open `/openclaw/` in new tab, sign in, reload dashboard; if still blank, follow iframe runbook. |
| 404 on `/openclaw/` | Insert Nginx OpenClaw block on PROD, reload nginx. |
| 504 on `/openclaw/` | **Automated (no SSH):** From your machine run `./scripts/openclaw/fix_504_via_eice.sh` (uses EC2 Instance Connect). Or **GitHub Actions → Fix OpenClaw 504 (EICE)** (manual or runs 06:00/18:00 UTC). **On PROD:** `cd /home/ubuntu/crypto-2.0 && sudo bash scripts/openclaw/fix_504_on_prod.sh`. Then test https://dashboard.hilovivo.com/openclaw/ (expect 401). If still 504, see OPENCLAW_504_UPSTREAM_DIAGNOSIS and ensure LAB is running OpenClaw and SG allows PROD→LAB:8081. |

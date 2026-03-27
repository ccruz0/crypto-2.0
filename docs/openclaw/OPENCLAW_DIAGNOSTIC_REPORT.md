# OpenClaw diagnostics report

**Generated:** from repo root (SSM check attempted).  
**Scope:** Inspect only; no infrastructure or configuration changes.

---

## 1. Script verification

| Script | Status |
|--------|--------|
| `scripts/openclaw/run_openclaw_check_via_ssm.sh` | ✅ Present |
| `scripts/openclaw/check_and_start_openclaw.sh` | ✅ Present |
| `scripts/openclaw/run_504_diagnosis_ssm.sh` | ✅ Present |

---

## 2. SSM check result

**Command run:** `bash scripts/openclaw/run_openclaw_check_via_ssm.sh` (from repo root)

**Output:**
```
=== OpenClaw check/start via SSM (Dashboard instance i-087953603011543c5) ===
SSM PingStatus: ConnectionLost
Instance not Online for SSM. Use EC2 Instance Connect or fix SSM; or run the script on the server: sudo bash scripts/openclaw/check_and_start_openclaw.sh
```

**Exit code:** 1

Remote diagnostics were **not** run because the Dashboard (PROD) instance is not reachable via SSM (ConnectionLost).

---

## 3. Manual commands (run on servers when SSM is unavailable)

### PROD (dashboard host)

Run on the machine serving https://dashboard.hilovivo.com (e.g. atp-rebuild-2026):

```bash
cd /home/ubuntu/crypto-2.0

sudo nginx -T 2>/dev/null | sed -n '/openclaw/,/}/p'

curl -I https://dashboard.hilovivo.com/openclaw/

curl -I https://dashboard.hilovivo.com/openclaw/ws
```

### LAB (OpenClaw host)

Run on the instance where OpenClaw is expected to run (e.g. atp-lab-ssm-clean or the host whose private IP is used in nginx upstream):

```bash
cd /home/ubuntu/crypto-2.0

sudo systemctl status openclaw --no-pager

sudo ss -lntp | grep 8081

curl -I http://127.0.0.1:8081/
```

---

## 4. Diagnostic summary (current state)

| Section | Result |
|---------|--------|
| **OpenClaw service status** | Not run (SSM ConnectionLost). Run manual LAB commands above to see `systemctl status openclaw`. |
| **Port listening check** | Not run. On LAB, run `sudo ss -lntp | grep 8081` to confirm 8081 is listening. |
| **Local endpoint response** | Not run. On LAB, run `curl -I http://127.0.0.1:8081/` — expect 200/302. |
| **Nginx proxy configuration detected** | Not run. On PROD, run `sudo nginx -T 2>/dev/null \| sed -n '/openclaw/,/}/p'` to see the openclaw block and upstream IP/port. |
| **HTTP response from /openclaw** | Not run. On PROD or from anywhere, run `curl -I https://dashboard.hilovivo.com/openclaw/` — 200/302 = OK, 404 = block missing, 504 = upstream unreachable. |
| **HTTP response from /openclaw/ws** | Not run. Run `curl -I https://dashboard.hilovivo.com/openclaw/ws` — 101 = WebSocket upgrade OK. |

---

## 5. Classification

**Current classification:** **Unable to determine remotely**

Reason: SSM PingStatus for the Dashboard instance (i-087953603011543c5) is **ConnectionLost**. No remote checks were executed.

After you run the manual commands above, use this table:

| Category | When it applies |
|----------|------------------|
| **A. Nginx block missing** | `nginx -T` shows no openclaw block, or `curl -I .../openclaw/` returns 404. |
| **B. Upstream unreachable (504)** | `curl -I .../openclaw/` returns 504; nginx block exists but upstream (LAB IP:port) does not respond. |
| **C. OpenClaw service not running** | On LAB, `systemctl status openclaw` is inactive/failed, or nothing listens on 8081. |
| **D. WebSocket misconfiguration** | `/openclaw/` returns 200 but `/openclaw/ws` fails or browser uses ws://localhost; fix in ccruz0/openclaw frontend. |
| **E. Everything appears healthy** | openclaw active on LAB, 8081 listening, nginx block present, curl to /openclaw/ and /openclaw/ws OK. |

---

## 6. NEXT ACTION

Because SSM is ConnectionLost, the next step is **one of**:

1. **Run manual commands and re-assess**  
   - On **PROD:** run the PROD block above, capture output.  
   - On **LAB:** run the LAB block above, capture output.  
   - Paste outputs into this report (or a follow-up) to classify as A–E and decide the exact fix.

2. **Restore SSM on the Dashboard instance**, then re-run the automated check:  
   ```bash
   cd /Users/carloscruz/crypto-2.0
   bash scripts/openclaw/run_openclaw_check_via_ssm.sh
   ```  
   See: `docs/aws/RUNBOOK_SSM_PROD_CONNECTION_LOST.md` (or equivalent) for SSM recovery.

3. **If you have SSH/EC2 Instance Connect to PROD only**  
   Run the PROD commands on the dashboard host, then run the LAB commands from any host that can reach LAB (e.g. from PROD if it can reach LAB’s private IP, or from a jump host).

**Recommended:** Run the **PROD** and **LAB** manual command blocks above, paste the outputs, then apply the fix for the resulting category (A–E).

# Dashboard + OpenClaw recovery order

Use this when **dashboard.hilovivo.com** times out **and/or** **/openclaw/** returns 502.

## Order (do not skip)

### A — Dashboard unreachable (ERR_TIMED_OUT)

1. **From your Mac** (AWS CLI configured):
   ```bash
   cd ~/crypto-2.0
   AUTO_START=1 AUTO_REBOOT=1 ./scripts/aws/bringup_dashboard_prod.sh
   ```
2. Wait **3–5 minutes** after start/reboot.
3. Reload **https://dashboard.hilovivo.com**. If only your Wi‑Fi fails, try **mobile hotspot** (network path).
4. If DNS still points to an old IP after stop/start → update **A record** to current public IP or attach **Elastic IP** (see `DASHBOARD_UNREACHABLE_RUNBOOK.md`).

### A2 — ERR_CONNECTION_CLOSED on /openclaw/ (pending, 0 B)

Connection dropped immediately — often wedged nginx worker or bad proxy state.

**From your Mac (no SSM):**
```bash
cd ~/crypto-2.0
./scripts/aws/heal_nginx_connection_closed_eice.sh
```
This SSHs to PROD via Instance Connect, **restarts nginx**, and **re-syncs** all openclaw `proxy_pass` lines to LAB:8080.

### B — Dashboard loads but /openclaw/ is 502

1. **On PROD** (EC2 Instance Connect to atp-rebuild-2026):
   ```bash
   curl -sSL https://raw.githubusercontent.com/ccruz0/crypto-2.0/main/scripts/openclaw/force_openclaw_proxy_8080_on_prod.sh | sudo bash
   ```
2. Or after `git pull` in repo on PROD:
   ```bash
   sudo bash scripts/openclaw/force_openclaw_proxy_8080_on_prod.sh
   ```
3. Expect **401** on `https://dashboard.hilovivo.com/openclaw/` (then Basic Auth).

### C — LAB / SSM (optional, when A+B are OK)

- **SSM ConnectionLost:** `docs/aws/RUNBOOK_SSM_PROD_CONNECTION_LOST.md`
- **Start OpenClaw on LAB:** Console → LAB → Instance Connect →  
  `NONINTERACTIVE=1 sudo bash scripts/openclaw/check_and_start_openclaw.sh`  
  (repo path may be `automated-trading-platform` after `git clone … crypto-2.0.git automated-trading-platform`)

## Quick verify (Mac)

```bash
./scripts/aws/verify_prod_public.sh
./scripts/openclaw/run_openclaw_diagnosis_local.sh
```

- API health **200** = dashboard stack up.
- `/openclaw/` **401** = proxy + upstream OK.

## Reference

| Doc / script | Use |
|--------------|-----|
| `scripts/aws/bringup_dashboard_prod.sh` | Start/reboot PROD, DNS warning |
| `docs/runbooks/DASHBOARD_UNREACHABLE_RUNBOOK.md` | Timeout deep dive |
| `docs/openclaw/README.md` | OpenClaw index + 502 notes |
| `scripts/openclaw/force_openclaw_proxy_8080_on_prod.sh` | Fix 502 when PROD→LAB curl works |

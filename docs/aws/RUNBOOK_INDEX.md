# AWS / Ops — Runbook index

One-line index: when to use each doc. PROD = atp-rebuild-2026 (i-087953603011543c5).

---

## This folder (docs/aws)

| Doc | When to use |
|-----|-------------|
| [COMANDOS_PARA_EJECUTAR.md](COMANDOS_PARA_EJECUTAR.md) | Copy-paste: reboot PROD (SSM), prod_status, deploy trigger, OpenClaw on LAB. |
| [AWS_PROD_QUICK_REFERENCE.md](AWS_PROD_QUICK_REFERENCE.md) | Instance IDs, secrets, scripts, workflows; first place to look. |
| [HOW_TO_CONNECT.md](HOW_TO_CONNECT.md) | **How to connect** to PROD and LAB: Console (EC2 Instance Connect), SSM, SSH, EICE; fix 504 from Console. |
| [CURSOR_SSH_AWS.md](CURSOR_SSH_AWS.md) | Cómo Cursor (terminal en tu Mac) se conecta por SSH a EC2 para ejecutar código en AWS; ~/.ssh/config, alias, clave .pem. |
| [POST_DEPLOY_VERIFICATION.md](POST_DEPLOY_VERIFICATION.md) | After a deploy or EC2_HOST change; first-deploy checklist; troubleshooting. |
| [RUNBOOK_SSM_PROD_CONNECTION_LOST.md](RUNBOOK_SSM_PROD_CONNECTION_LOST.md) | PROD SSM PingStatus = ConnectionLost: reboot + diagnose. |
| [PROD_ACCESS_WHEN_SSM_AND_SSH_FAIL.md](PROD_ACCESS_WHEN_SSM_AND_SSH_FAIL.md) | SSM Offline and Instance Connect fails: use **EC2 Serial Console** to start sshd + SSM agent. |
| [RUNBOOK_SSM_FIX_AND_INJECT_SSH_KEY.md](RUNBOOK_SSM_FIX_AND_INJECT_SSH_KEY.md) | Need SSH to PROD when key is lost; inject key via SSM. |
| [AWS_BRINGUP_RUNBOOK.md](AWS_BRINGUP_RUNBOOK.md) | Bring-up, verification, and troubleshooting on the instance (copy-paste). |
| [TELEGRAM_KEY_ROTATION_RUNBOOK.md](TELEGRAM_KEY_ROTATION_RUNBOOK.md) | Rotate Telegram encryption key / token (quarterly or post-compromise). |
| [AWS_ARCHITECTURE.md](AWS_ARCHITECTURE.md) | Target architecture, roles, SSM, VPC. |
| [AWS_LIVE_AUDIT.md](AWS_LIVE_AUDIT.md) | Last live audit snapshot; commands to re-run on instances. |
| [IMDSV2_REQUIRED_RUNBOOK.md](IMDSV2_REQUIRED_RUNBOOK.md) | Clear EC2 “IMDSv2 recommended” warning: enable required + code already uses IMDSv2. |

---

## Other folders

| Doc | When to use |
|-----|-------------|
| [../audit/AWS_STATE_AUDIT.md](../audit/AWS_STATE_AUDIT.md) | Full AWS state audit (repo vs live); CLI commands; decision log. |
| [../audit/EC2_OPENCLAW_INSTANCE_AND_CONSISTENCY_AUDIT.md](../audit/EC2_OPENCLAW_INSTANCE_AND_CONSISTENCY_AUDIT.md) | Instance mapping (PROD vs LAB/OpenClaw), docs/code/nginx consistency, verification commands. |
| [../audit/INSTANCE_ARCHITECTURE_CONSISTENCY_AUDIT.md](../audit/INSTANCE_ARCHITECTURE_CONSISTENCY_AUDIT.md) | Full instance + architecture audit; old IP refs (file:line); nginx/docker/secrets; P0/P1/P2 remediation. |
| [../runbooks/DASHBOARD_AND_OPENCLAW_RECOVERY_ORDER.md](../runbooks/DASHBOARD_AND_OPENCLAW_RECOVERY_ORDER.md) | **Start here** when dashboard times out and/or /openclaw/ 502: bringup script → force proxy → LAB. |
| [../runbooks/DASHBOARD_UNREACHABLE_RUNBOOK.md](../runbooks/DASHBOARD_UNREACHABLE_RUNBOOK.md) | ERR_TIMED_OUT deep dive: SG, DNS, Elastic IP, reboot, hotspot. |
| [../runbooks/INSTANCE_SOURCE_OF_TRUTH.md](../runbooks/INSTANCE_SOURCE_OF_TRUTH.md) | Definitive PROD/LAB table (IPs, IDs, access, verification). |
| [../audit/RUNBOOK_ARCH_B_PROD_LAB.md](../audit/RUNBOOK_ARCH_B_PROD_LAB.md) | Create atp-prod-sg / atp-lab-sg; IAM; harden PROD/LAB separation. |
| [../audit/SSM_SESSION_MANAGER_CONNECTIVITY_AUDIT.md](../audit/SSM_SESSION_MANAGER_CONNECTIVITY_AUDIT.md) | Deep SSM/Session Manager diagnosis when runbook reboot didn’t fix it. |
| [../audit/RUNBOOK_EGRESS_OPTION_A1.md](../audit/RUNBOOK_EGRESS_OPTION_A1.md) | Restrict egress to 443, 80→metadata, 53. After applying: Ubuntu apt needs HTTPS — see §3.1 or `scripts/aws/apt-sources-https.sh` (run on instance via SSM). |
| [../openclaw/SIGUIENTE_PASOS_OPENCLAW.md](../openclaw/SIGUIENTE_PASOS_OPENCLAW.md) | Deploy OpenClaw on LAB (atp-lab-ssm-clean). |
| [../openclaw/RUNBOOK_OPENCLAW_LAB.md](../openclaw/RUNBOOK_OPENCLAW_LAB.md) | OpenClaw en LAB: pasos copy-paste (conexión, token, .env.lab, compose). |
| [../openclaw/LAB_SETUP_AND_VALIDATION.md](../openclaw/LAB_SETUP_AND_VALIDATION.md) | OpenClaw token, Git, API permission tests on LAB. |
| [../openclaw/DEPLOY_OPENCLAW_NGINX_PROD.md](../openclaw/DEPLOY_OPENCLAW_NGINX_PROD.md) | Deploy /openclaw/ block on dashboard Nginx (script + manual); duplicate default server, htpasswd. |
| [../runbooks/OPENCLAW_BASIC_AUTH_PASSWORD_CHANGE.md](../runbooks/OPENCLAW_BASIC_AUTH_PASSWORD_CHANGE.md) | Change Basic Auth password for /openclaw/ (htpasswd on PROD; user admin). |
| [../runbooks/DEPLOY_REAL_OPENCLAW_APP_ON_LAB.md](../runbooks/DEPLOY_REAL_OPENCLAW_APP_ON_LAB.md) | Replace placeholder container with real OpenClaw app on LAB (OPENCLAW_IMAGE, down/pull/up). |
| [../runbooks/EC2_DASHBOARD_LIVE_DATA_FIX.md](../runbooks/EC2_DASHBOARD_LIVE_DATA_FIX.md) | Dashboard visible but health FAIL / no live data / "Invalid API key": ATP_API_KEY, market-updater, order_intents repair. |
| [../runbooks/EC2_SELFHEAL_DEPLOY.md](../runbooks/EC2_SELFHEAL_DEPLOY.md) | Deploy self-heal on EC2: git pull, systemd timer, .env fallback, 203/EXEC fix. |
| [../runbooks/EC2_FIX_MARKET_DATA_NOW.md](../runbooks/EC2_FIX_MARKET_DATA_NOW.md) | Fix market_data/market_updater FAIL now: restore verify.sh (emitter), .env, restart stack, update-cache, diagnose updater. |
| [../runbooks/ATP_HEALTH_ALERT_STREAK_FAIL.md](../runbooks/ATP_HEALTH_ALERT_STREAK_FAIL.md) | When Telegram shows "ATP Health Alert" streak_fail_3: interpret verify_label, market_data, market_updater; quick diagnostics and link to EC2_FIX_MARKET_DATA_NOW. |
| [../runbooks/OPENCLAW_AND_SYSTEM_HEALTH_DOWN.md](../runbooks/OPENCLAW_AND_SYSTEM_HEALTH_DOWN.md) | OpenClaw tab blank + System Health FAIL (Market, Updater, Monitor, Telegram): diagnosis script, fix health components, fix OpenClaw iframe (auth / proxy). |
| [../runbooks/TELEGRAM_ALERTS_NOT_SENT.md](../runbooks/TELEGRAM_ALERTS_NOT_SENT.md) | Notion task "Investigate Telegram alerts not being sent": run diagnose script, check block reasons (RUN_TELEGRAM, kill switch, token/chat_id, origin), fix and resolve task. |
| [../runbooks/NOTION_TASK_TO_CURSOR_AND_DEPLOY.md](../runbooks/NOTION_TASK_TO_CURSOR_AND_DEPLOY.md) | **Full flow:** Any Notion task → Cursor handoff → Run Cursor Bridge → deploy approval → deploy → smoke check → done. Use for end-to-end from task to new code deployment. |
| [../runbooks/OPENCLAW_COST_VERIFICATION_RUNBOOK.md](../runbooks/OPENCLAW_COST_VERIFICATION_RUNBOOK.md) | After enabling OpenClaw cost levers: run one Notion task, check logs for `openclaw_apply_cost` and usage; verify gateway returns token counts. |
| [../runbooks/EC2_DB_BOOTSTRAP.md](../runbooks/EC2_DB_BOOTSTRAP.md) | Create watchlist_items (and related tables): bootstrap schema before enabling self-heal timer; .env.aws fix. |
| [../runbooks/PROD_DISK_RESIZE.md](../runbooks/PROD_DISK_RESIZE.md) | **Increase PROD disk size:** EBS modify volume in Console, then growpart + resize2fs on instance (FAIL:DISK / no space left). |
| [../runbooks/LAB_DISK_RESIZE_OPENCLAW_REDEPLOY.md](../runbooks/LAB_DISK_RESIZE_OPENCLAW_REDEPLOY.md) | LAB disk full (no space for docker pull): EBS resize + growpart/resize2fs, then redeploy OpenClaw. |
| [../runbooks/OPENCLAW_ATP_ACCESS_AND_APPROVAL_FIX.md](../runbooks/OPENCLAW_ATP_ACCESS_AND_APPROVAL_FIX.md) | ATP connectivity via SSM API, Telegram approval dedup, investigation artifact persistence; root cause and validation. |

---

## Stability and diagnostics

See **[../runbooks/EC2_DB_BOOTSTRAP.md](../runbooks/EC2_DB_BOOTSTRAP.md)** § Diagnostics and stability: market fallback check (run in backend container, no prod data change), verify.sh DEGRADED (market_data WARN + market_updater PASS = OK), ensure_env_aws, and hourly health snapshot (install systemd timer; log at `/var/log/atp/health_snapshots.log`). **Telegram alerts (optional):** same runbook § [Telegram alerts (optional)](../runbooks/EC2_DB_BOOTSTRAP.md#telegram-alerts-optional) — enable health-snapshot failure alerts to Telegram; env from `secrets/runtime.env` / `.env` / `.env.aws`; test with `sudo systemctl start atp-health-alert.service` and `journalctl -u atp-health-alert.service -n 50`.

---

## If PROD (dashboard) is down

1. **Check from repo:** `./scripts/aws/prod_status.sh` → PROD API OK?
2. **Check Actions:** Last “Deploy to AWS EC2 (Session Manager)” and “Prod Health Check” runs — any failures?
3. **If API not 200:** You need access to PROD (SSM or SSH). Follow [RUNBOOK_SSM_PROD_CONNECTION_LOST.md](RUNBOOK_SSM_PROD_CONNECTION_LOST.md) if SSM is ConnectionLost; then on the instance run `docker compose --profile aws ps` and check nginx/backend logs.
4. **If SSM is Online:** Use Session Manager to open a shell on atp-rebuild-2026 and run [AWS_BRINGUP_RUNBOOK.md](AWS_BRINGUP_RUNBOOK.md) verification steps or [AWS_LIVE_AUDIT.md](AWS_LIVE_AUDIT.md) §2.
5. **If dashboard loads but health fails or no live data:** See [EC2_DASHBOARD_LIVE_DATA_FIX.md](../runbooks/EC2_DASHBOARD_LIVE_DATA_FIX.md) (ATP_API_KEY, market-updater, order_intents, repair).

---

## apt update fails (Network is unreachable)

If SSM works but `apt update` on the instance fails with "Network is unreachable" to Ubuntu mirrors, egress is likely restricted to 443 (no HTTP 80 to internet). **Fix:** Switch apt to HTTPS by running on the instance (via SSM): `bash scripts/aws/apt-sources-https.sh`, or see [RUNBOOK_EGRESS_OPTION_A1.md](../audit/RUNBOOK_EGRESS_OPTION_A1.md) §3.1.

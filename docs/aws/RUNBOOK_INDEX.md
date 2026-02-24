# AWS / Ops — Runbook index

One-line index: when to use each doc. PROD = atp-rebuild-2026 (i-087953603011543c5).

---

## This folder (docs/aws)

| Doc | When to use |
|-----|-------------|
| [COMANDOS_PARA_EJECUTAR.md](COMANDOS_PARA_EJECUTAR.md) | Copy-paste: reboot PROD (SSM), prod_status, deploy trigger, OpenClaw on LAB. |
| [AWS_PROD_QUICK_REFERENCE.md](AWS_PROD_QUICK_REFERENCE.md) | Instance IDs, secrets, scripts, workflows; first place to look. |
| [POST_DEPLOY_VERIFICATION.md](POST_DEPLOY_VERIFICATION.md) | After a deploy or EC2_HOST change; first-deploy checklist; troubleshooting. |
| [RUNBOOK_SSM_PROD_CONNECTION_LOST.md](RUNBOOK_SSM_PROD_CONNECTION_LOST.md) | PROD SSM PingStatus = ConnectionLost: reboot + diagnose. |
| [RUNBOOK_SSM_FIX_AND_INJECT_SSH_KEY.md](RUNBOOK_SSM_FIX_AND_INJECT_SSH_KEY.md) | Need SSH to PROD when key is lost; inject key via SSM. |
| [AWS_BRINGUP_RUNBOOK.md](AWS_BRINGUP_RUNBOOK.md) | Bring-up, verification, and troubleshooting on the instance (copy-paste). |
| [TELEGRAM_KEY_ROTATION_RUNBOOK.md](TELEGRAM_KEY_ROTATION_RUNBOOK.md) | Rotate Telegram encryption key / token (quarterly or post-compromise). |
| [AWS_ARCHITECTURE.md](AWS_ARCHITECTURE.md) | Target architecture, roles, SSM, VPC. |
| [AWS_LIVE_AUDIT.md](AWS_LIVE_AUDIT.md) | Last live audit snapshot; commands to re-run on instances. |

---

## Other folders

| Doc | When to use |
|-----|-------------|
| [../audit/AWS_STATE_AUDIT.md](../audit/AWS_STATE_AUDIT.md) | Full AWS state audit (repo vs live); CLI commands; decision log. |
| [../audit/RUNBOOK_ARCH_B_PROD_LAB.md](../audit/RUNBOOK_ARCH_B_PROD_LAB.md) | Create atp-prod-sg / atp-lab-sg; IAM; harden PROD/LAB separation. |
| [../audit/SSM_SESSION_MANAGER_CONNECTIVITY_AUDIT.md](../audit/SSM_SESSION_MANAGER_CONNECTIVITY_AUDIT.md) | Deep SSM/Session Manager diagnosis when runbook reboot didn’t fix it. |
| [../audit/RUNBOOK_EGRESS_OPTION_A1.md](../audit/RUNBOOK_EGRESS_OPTION_A1.md) | Restrict egress to 443, 80→metadata, 53. After applying: Ubuntu apt needs HTTPS — see §3.1 or `scripts/aws/apt-sources-https.sh` (run on instance via SSM). |
| [../openclaw/SIGUIENTE_PASOS_OPENCLAW.md](../openclaw/SIGUIENTE_PASOS_OPENCLAW.md) | Deploy OpenClaw on LAB (atp-lab-ssm-clean). |
| [../openclaw/RUNBOOK_OPENCLAW_LAB.md](../openclaw/RUNBOOK_OPENCLAW_LAB.md) | OpenClaw en LAB: pasos copy-paste (conexión, token, .env.lab, compose). |
| [../openclaw/LAB_SETUP_AND_VALIDATION.md](../openclaw/LAB_SETUP_AND_VALIDATION.md) | OpenClaw token, Git, API permission tests on LAB. |

---

## If PROD (dashboard) is down

1. **Check from repo:** `./scripts/aws/prod_status.sh` → PROD API OK?
2. **Check Actions:** Last “Deploy to AWS EC2” and “Prod Health Check” runs — any failures?
3. **If API not 200:** You need access to PROD (SSM or SSH). Follow [RUNBOOK_SSM_PROD_CONNECTION_LOST.md](RUNBOOK_SSM_PROD_CONNECTION_LOST.md) if SSM is ConnectionLost; then on the instance run `docker compose --profile aws ps` and check nginx/backend logs.
4. **If SSM is Online:** Use Session Manager to open a shell on atp-rebuild-2026 and run [AWS_BRINGUP_RUNBOOK.md](AWS_BRINGUP_RUNBOOK.md) verification steps or [AWS_LIVE_AUDIT.md](AWS_LIVE_AUDIT.md) §2.

---

## apt update fails (Network is unreachable)

If SSM works but `apt update` on the instance fails with "Network is unreachable" to Ubuntu mirrors, egress is likely restricted to 443 (no HTTP 80 to internet). **Fix:** Switch apt to HTTPS by running on the instance (via SSM): `bash scripts/aws/apt-sources-https.sh`, or see [RUNBOOK_EGRESS_OPTION_A1.md](../audit/RUNBOOK_EGRESS_OPTION_A1.md) §3.1.

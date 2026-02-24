# AWS docs and runtime dashboard

This folder holds AWS architecture, audit, remediation, and the **runtime status dashboard** for production (atp-rebuild-2026) and lab (atp-lab-ssm-clean).

---

## Runtime dashboard — where to look

### Guard and Sentinel runs

| Workflow | When it runs | Where to open |
|----------|----------------|----------------|
| **AWS Runtime Guard** | On push to `main`, or manually (workflow_dispatch) | Repo **Actions** tab → select **AWS Runtime Guard** |
| **AWS Runtime Sentinel** | Daily 02:00 UTC, or manually (workflow_dispatch) | Repo **Actions** tab → select **AWS Runtime Sentinel** |

- Workflow definitions: [.github/workflows/aws-runtime-guard.yml](../../.github/workflows/aws-runtime-guard.yml), [.github/workflows/aws-runtime-sentinel.yml](../../.github/workflows/aws-runtime-sentinel.yml).
- Sentinel uploads the **runtime-sentinel-artifacts** artifact every run; download it to get `runtime-report.json` and `runtime-history/`.

### How to read `runtime-report.json`

After downloading the Sentinel artifact, open `runtime-report.json`:

| Field | Meaning |
|-------|--------|
| **classification** | `PRODUCTION_SAFE` \| `PRODUCTION_AT_RISK` \| `CRITICAL_RUNTIME_VIOLATION` |
| **ssm_status** | `ok` or `failed` (SSM command reached the instance or not) |
| **ssm_status_details** | When failed: concrete reason (e.g. Undeliverable, ConnectionLost). Use this to know why SSM didn’t run. |
| **remediation.attempted** | `true` if a containment run was executed (only when CRITICAL and ALLOW_AUTO_KILL=true). |
| **remediation.status** | `skipped` \| `ok` \| `failed`. If `attempted` and `failed`, containment did not succeed (e.g. SSM still unreachable). |
| **remediation.next_step** | Human-readable next action (e.g. “Restore SSM connectivity for atp-rebuild-2026 (…) then re-run verification.”). Always check this when status is not SAFE. |
| **checks** | `telegram_poller_ok`, `scheduler_ok`, `exposed_ports_ok`, etc. |

**Edge case (SSM Undeliverable + auto-kill):** If the first run is CRITICAL due to SSM Undeliverable and ALLOW_AUTO_KILL=true, the second run will also fail (no SSM). The report will show `remediation.attempted: true`, `remediation.status: failed`, and `remediation.next_step` telling you to restore SSM — so it’s clear that containment was not achieved.

---

## Quick verification checklist (after a Sentinel run)

1. **Outputs in log** — In the “Run AWS runtime verification” step log you should see:  
   `Recorded exitcode=0|1|2 to GITHUB_OUTPUT (...)`  
   Later steps (e.g. “Fail job if not safe”) show the condition evaluated with that value.
2. **Verify step never dies from exit code** — The step uses `set +e` before the script and `set -e` after capturing `code=$?`, so the step always reaches the `echo … >> GITHUB_OUTPUT` and `exit 0`.
3. **Auto-kill with SSM Undeliverable** — In the artifact, if CRITICAL + ALLOW_AUTO_KILL: `remediation.attempted=true`, `remediation.status=failed`, `remediation.next_step` set; no “fake” containment.
4. **Job fails with correct code** — Step “Run AWS runtime verification” is green (exits 0). Artifacts are uploaded. If exitcode ≠ 0, the last step “Fail job if not safe” fails and the job ends with exit code 1 or 2.

---

## Other docs in this folder

- [COMANDOS_PARA_EJECUTAR.md](COMANDOS_PARA_EJECUTAR.md) — **Comandos copy-paste:** reboot PROD (SSM), estado, deploy, OpenClaw en LAB.
- [RUNBOOK_INDEX.md](RUNBOOK_INDEX.md) — **Index:** when to use each runbook; "If PROD is down" steps.
- [AWS_PROD_QUICK_REFERENCE.md](AWS_PROD_QUICK_REFERENCE.md) — **Referencia rápida:** instancias, secrets, scripts, workflows, runbooks.
- [AWS_BRINGUP_RUNBOOK.md](AWS_BRINGUP_RUNBOOK.md) — **Single operator script** for bring-up, verification, and troubleshooting (copy-paste safe; uses `--profile aws`).
- [RUNBOOK_SSM_PROD_CONNECTION_LOST.md](RUNBOOK_SSM_PROD_CONNECTION_LOST.md) — PROD (atp-rebuild-2026) SSM ConnectionLost: reboot + diagnóstico.
- [POST_DEPLOY_VERIFICATION.md](POST_DEPLOY_VERIFICATION.md) — Verificación tras deploy (Prod Health Check workflow, Actions, scripts locales, SSM).
- [TELEGRAM_KEY_ROTATION_RUNBOOK.md](TELEGRAM_KEY_ROTATION_RUNBOOK.md) — Quarterly (or post-compromise) rotation of the Telegram encryption key and optional token.
- [AWS_ARCHITECTURE.md](AWS_ARCHITECTURE.md) — Target architecture and roles.
- [AWS_LIVE_AUDIT.md](AWS_LIVE_AUDIT.md) — Last live audit snapshot.
- [../audit/AWS_STATE_AUDIT.md](../audit/AWS_STATE_AUDIT.md) — **Auditoría estado AWS** (repositorio + CI vs docs); incluye comandos para verificación viva y hallazgos (instance ID en workflows vs PROD documentada).

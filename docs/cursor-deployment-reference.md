# Cursor Deployment Reference (Production)

This guide defines the validated, deterministic deployment flow for the Automated Trading Platform. It assumes you run commands locally on your machine (not from Cursor) with your own SSH access and environment.

## 1) SSH Validator Rules
- Operational scope (only these are validated):
  - `scripts/*.sh`
  - `deploy_*.sh`
  - `backend/*.sh`
- Ignored (never flagged):
  - `node_modules`, `examples`, `docs`, `test`, `tests`, `__tests__`, `tmp`, `.github`, `.vscode`, `assets`, `static`, `public`, `scripts/archive`, `scripts/experimental`
  - Markdown/JS/TS files and any non-deployment file
  - Echo, comments, heredocs, or string literals inside `.sh`
- Violations only when an executable line starts with: `ssh`, `scp`, `rsync`, `ssh-agent`, `ssh-add` (and `.pem` only when used in executable code).
- Helper sourcing: operational scripts must source `scripts/ssh_key.sh` if they execute remote ops; and use `ssh_cmd`, `scp_cmd`, `rsync_cmd` (never raw ssh/scp/rsync).

## 2) DRY_RUN Rules
- DRY_RUN prints the exact commands that would run (order, SSH target, paths), skips sleeps/timeouts, and never executes remote actions.
- Two DRY_RUN flows:
  - `./scripts/pre_deploy_check.sh` → Validator + DRY_RUN of `start-stack-and-health.sh` and `start-aws-stack.sh`.
  - `./scripts/simulate_deploy.sh` → End-to-end simulation: runs the pre-check and both start scripts in DRY_RUN.
- PASS criteria: 0 violations, deterministic command sequence displayed, no remote execution.

## 3) Deployment Flow (Production)
1. Verify commit:
   ```bash
   git rev-parse HEAD
   # Must match the target commit (e.g., 4330ffd3e30b60b17e537c5930aa0de950401917)
   ```
2. Deploy with auto-confirmation:
   ```bash
   printf 'y\n' | SERVER=175.41.189.249 ./scripts/deploy_production.sh
   ```
   - Runs pre-flight validation (locally), prompts for confirmation (auto-confirmed by printf), then starts stack and health monitors on the remote host using the unified SSH system.

## 4) Simulation Flow (Pre-flight)
- Quick validator:
  ```bash
  ./scripts/test_ssh_system.sh
  ```
- Pre-deploy DRY_RUN:
  ```bash
  DRY_RUN=1 ./scripts/pre_deploy_check.sh
  ```
- Full simulation:
  ```bash
  DRY_RUN=1 ./scripts/simulate_deploy.sh
  ```

## 5) “Never Deploy Unless DRY_RUN Passes”
- Rule: Do not deploy to AWS unless both DRY_RUN flows pass with 0 violations.

## 6) Post-Deployment Verification
- Health:
  ```bash
  curl -k https://dashboard.hilovivo.com/api/health
  ```
- LIVE/DRY:
  ```bash
  curl -k https://dashboard.hilovivo.com/api/trading/live-status
  ```
- Dashboard state:
  ```bash
  curl -k https://dashboard.hilovivo.com/api/dashboard/state
  ```
- Healthy means:
  - `backend-aws` and `frontend-aws` are “Up” (`docker compose --profile aws ps` on server).
  - `/api/health` returns JSON immediately (HTTP 200).
  - `/api/trading/live-status` returns JSON with `ok:true`, `success:true`, `mode` is `LIVE` or `DRY_RUN`.
  - `/api/dashboard/state` returns data without timeouts.

## 7) Troubleshooting (Minimal)
- Compose status & backend logs:
  ```bash
  ssh -o StrictHostKeyChecking=no ubuntu@175.41.189.249 \
    'cd /home/ubuntu/automated-trading-platform && docker compose --profile aws ps && docker compose --profile aws logs --tail=200 backend-aws'
  ```
- Nginx status & logs:
  ```bash
  ssh -o StrictHostKeyChecking=no ubuntu@175.41.189.249 'sudo systemctl is-active nginx || sudo systemctl restart nginx'
  ssh -o StrictHostKeyChecking=no ubuntu@175.41.189.249 'sudo tail -n 200 /var/log/nginx/error.log && sudo tail -n 200 /var/log/nginx/access.log'
  ```
- Common diagnoses:
  - Backend not listening: check `backend-aws` health/logs; restart container.
  - Port mapping broken: verify docker compose ports and Nginx upstream proxy to 127.0.0.1:8002.
  - Nginx misconfigured: ensure `location = /api/health` proxies to backend `__ping` before general `/api` block.

## 8) Final Production Command
```bash
SERVER=175.41.189.249 ./scripts/deploy_production.sh
```
This re-runs pre-flight checks, asks for explicit confirmation, and then applies the deployment. Use the verification commands above to confirm health immediately after. 





# Deploy disk-capacity guard

Prevents `no space left on device` during the production Docker build, so
deployments complete without manual disk cleanup and without risking
availability.

## Problem

The deploy builds a fresh image set with `docker compose build` **while the
previous stack keeps running** (deploy resiliency / "Outcome B"). On the small
(~29 GB) root volume the new layers + retained old images can exceed free space,
killing the build with `no space left on device`. The new image is never
produced, so production stays on the previous SHA.

The daily cleanup cron (`infra/cleanup_disk.sh`, 02:00) and the post-`up`
prune both run at the wrong moment — never right before the build.

## Fix

`scripts/aws/predeploy_disk_guard.sh` runs **immediately before** the build
(wired into `.github/workflows/deploy_session_manager.yml` and
`scripts/deploy_aws.sh`). It reclaims space idempotently and
production-safely.

### Reclamation tiers

| Tier | When | What it removes |
|------|------|-----------------|
| 1 (always) | every deploy | dangling images, build cache >24h, stopped containers, unused networks, container json logs, journal >5d, apt cache, app logs >5 MB/>5 d (via `infra/cleanup_disk.sh`) |
| 2 (escalation) | only if free `< MIN_FREE_GB` after Tier 1 | **all** images not referenced by any container + full build cache |

### Safety guarantees

- **Never** removes named volumes — no `docker volume prune`, no `-v`, no
  `docker system prune --volumes`. Postgres / Prometheus / Grafana data is safe.
- **Never** removes images in use by a running *or* stopped container (Docker
  protects these), so the live stack being kept up during the build is safe.
- **Never** runs `docker compose down`; never restarts containers.
- Best-effort: a failing reclaim step never aborts the deploy.

## Configuration (env vars)

| Var | Default | Meaning |
|-----|---------|---------|
| `MIN_FREE_GB` | `6` | Free-space floor; Tier 2 triggers below it |
| `DISK_GUARD_STRICT` | `0` | `1` → exit 1 if still below floor (deploy aborts; old stack keeps serving) |
| `DISK_GUARD_DRY_RUN` | `0` | `1` → report + decide tiers, run no destructive command (CI/testing) |
| `DISK_GUARD_MOUNT` | `/` | Volume to measure |
| `DISK_GUARD_LOG` | `/tmp/atp-predeploy-disk.log` | Log file |
| `DISK_GUARD_METRICS_DIR` | `/var/lib/node_exporter/textfile_collector` | node_exporter textfile metrics (written only if dir exists) |

## Monitoring / verification output

- Logs `BEFORE` / `AFTER` free GB + used %, `docker system df`, reclaimed GB,
  and a `PASS` / `INSUFFICIENT` verdict to stdout and `DISK_GUARD_LOG`.
- If the node_exporter textfile collector dir exists, writes
  `atp_predeploy_disk.prom` with `atp_predeploy_disk_free_gb`,
  `atp_predeploy_disk_used_percent`, `atp_predeploy_disk_guard_ok`,
  `atp_predeploy_disk_guard_run_timestamp_seconds`.

## Manual run

```bash
# On PROD
cd /home/ubuntu/crypto-2.0
bash scripts/aws/predeploy_disk_guard.sh                 # normal
MIN_FREE_GB=8 bash scripts/aws/predeploy_disk_guard.sh   # higher floor
DISK_GUARD_DRY_RUN=1 bash scripts/aws/predeploy_disk_guard.sh   # preview only

# Or remotely via SSM (existing helper, AGGRESSIVE optional)
bash scripts/aws/prod_free_disk_via_ssm.sh
```

## If the guard reports INSUFFICIENT

All safe space has been reclaimed and the remainder is named volumes /
running-stack images / OS. **Do not delete volumes.** Grow the EBS root volume —
see [`PROD_DISK_RESIZE.md`](./PROD_DISK_RESIZE.md).

## Rollback

The change is additive (one new script + two call sites). To disable without
reverting: set `MIN_FREE_GB=0` (Tier 2 never triggers; Tier 1 == existing daily
cleanup) or revert the two call-site lines in
`.github/workflows/deploy_session_manager.yml` and `scripts/deploy_aws.sh`.
No data migration; nothing to undo on disk.

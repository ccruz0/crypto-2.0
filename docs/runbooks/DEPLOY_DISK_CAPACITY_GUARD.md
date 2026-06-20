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
| 1 (always) | every deploy | dangling images, **all build cache** (`docker builder prune -af`), stopped containers, unused networks, container json logs, journal >5d, apt cache, app logs, **stale `/tmp/jarvis-sandbox` dirs >12h** (via `infra/cleanup_disk.sh`) |
| 2 (escalation) | only if free `< MIN_FREE_GB` after Tier 1 | **all** images not referenced by any container + full build cache |

### What actually fills the PROD disk (measured)

On a lean PROD host the standard `docker image prune` reclaims **~0** because
almost every image is in use. The real, recurring consumers — which the old
daily cron and post-`up` prune missed — are:

1. **Build cache from `--no-cache` / failed builds.** A failed build leaks its
   partial layers/cache into `/var/lib/containerd`; the old cleanup only pruned
   cache `>24h`, so same-day cache (often **2–3 GB**) survived. The guard and the
   post-`up` step now run `docker builder prune -af` (no age filter).
2. **`/tmp/jarvis-sandbox`** coding-workflow sandboxes (each hundreds of MB of
   `node_modules`); nothing reclaimed them. Now cleaned (idle >12h) by Tier 1 and
   the daily cron.
3. **Image bloat** from baking `.git`, runtime artifacts, logs, tests, and
   caches into the backend-aws image. A root `.dockerignore` (affects only the
   context-`.` backend-aws build) trims this — backend-aws dropped 1.19 GB → 1.07 GB.

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

### EBS resize requires admin credentials

The PROD instance role (`EC2_SSM_Role`) does **not** have `ec2:ModifyVolume`, so
the volume cannot be grown from the instance itself. Growing it (the permanent
fix when the host is genuinely full of legitimate data) must be done with an AWS
account/role that has `ec2:ModifyVolume`:

```bash
# 30 GiB -> 50 GiB (vol-07912c5ce394ed1ae is PROD i-087953603011543c5's root)
aws ec2 modify-volume --volume-id vol-07912c5ce394ed1ae --size 50 --region ap-southeast-1
# wait for "optimizing"/"completed", then on the instance:
sudo growpart /dev/nvme0n1 1 && sudo resize2fs /dev/nvme0n1p1 && df -h /
```

## Rollback

The change is additive (one new script + two call sites). To disable without
reverting: set `MIN_FREE_GB=0` (Tier 2 never triggers; Tier 1 == existing daily
cleanup) or revert the two call-site lines in
`.github/workflows/deploy_session_manager.yml` and `scripts/deploy_aws.sh`.
No data migration; nothing to undo on disk.

# PROD swap file (memory hardening)

**Purpose:** Add a small swap file on the PROD EC2 instance to improve resilience when memory is tight. This is a **safety margin** improvement only; it does not replace proper scaling or AWS recovery.

**Instance:** PROD (e.g. i-087953603011543c5, atp-rebuild-2026)  
**Default swap size:** 2 GB (overridable via `SWAP_SIZE_GB`)

---

## Why this change

After the **2026-03-11 PROD incident**, we confirmed:

- The failure was **instance-level** (EC2 reachability, SSM, then app unreachable); reboot and ext4 recovery restored service.
- We added **infrastructure-level EC2 auto-recovery** so AWS can recover the instance when status checks fail.
- On PROD, **memory is tight** on a t3.small (e.g. ~1.9 GiB total, ~125 MiB free, **swap disabled**). No-swap on a small Docker host increases the risk of OOM under load and makes the instance more fragile.

Adding a small swap file is the **next safest improvement**: it gives the kernel a buffer so short memory spikes are less likely to trigger OOM or unresponsive behavior, without changing any ATP application or health logic.

See:

- **docs/runbooks/PROD_SWAP_DEPLOYMENT_RUNBOOK.md** — step-by-step deployment, verification, and rollback on PROD.
- **docs/PROD_INCIDENT_2026-03-11_RECOVERY.md** — incident summary and recommendations.
- **docs/ATP_RUNTIME_HEALTH_RECOVERY_BASELINE.md** — current PROD runtime state.

---

## What this is (and is not)

- **Is:** A **safety margin** for a small instance: 2 GB swap at `/swapfile`, persisted across reboot.
- **Is not:** A replacement for proper instance sizing, EC2 auto-recovery, or memory-pressure monitoring. It does **not** change docker, nginx, backend, timers, or existing health/recovery scripts.

---

## Deployment

**Operational runbook:** For the full step-by-step procedure (connect, update repo, run script, verify, optional swappiness, final health check, rollback), use **docs/runbooks/PROD_SWAP_DEPLOYMENT_RUNBOOK.md**.

**Exact deploy sequence on PROD:**

1. **Repo on PROD must be updated first** if the folder `infra/aws/prod_swap` does not exist yet. On the PROD instance: `cd ~/automated-trading-platform && git pull`, then `ls infra/aws/prod_swap` to confirm.
2. **Run swap setup:**
   ```bash
   cd ~/automated-trading-platform/infra/aws/prod_swap
   sudo ./setup_swap.sh
   ```
   Optional size: `sudo SWAP_SIZE_GB=1 ./setup_swap.sh`
3. **Idempotent:** If swap is already enabled, the script exits successfully without changing anything.

**Optional — lower swappiness (recommended):** Use swap only as a safety buffer; prefer RAM first:

```bash
echo "vm.swappiness=10" | sudo tee /etc/sysctl.d/99-atp-swappiness.conf
sudo sysctl -p /etc/sysctl.d/99-atp-swappiness.conf
```

**Final health check after swap deployment:** See runbook §6. In short: `free -h`, `docker ps`, `systemctl is-active nginx`, `systemctl is-active snap.amazon-ssm-agent.amazon-ssm-agent`, `curl -sS https://dashboard.hilovivo.com/api/health`. Expect nginx and SSM active, API healthy, docker still running.

---

## Verification

After running the script (exact commands):

```bash
swapon --show
free -h
grep swapfile /etc/fstab
```

**Expected:** `/swapfile` listed in `swapon` with size ~2G; Swap row in `free -h` with non-zero Total/Free; `/etc/fstab` contains the line `/swapfile none swap sw 0 0`.

---

## Rollback

To remove swap and the file:

```bash
sudo swapoff /swapfile
sudo rm -f /swapfile
sudo sed -i '\|^/swapfile |d' /etc/fstab
```

Then confirm with `swapon --show` (empty) and `free -h` (Swap 0).

---

## Constraints

- No changes are made to ATP health scripts, docker-compose, nginx, backend, timers, or EC2 auto-recovery configuration. This is an isolated, reversible OS-level change.

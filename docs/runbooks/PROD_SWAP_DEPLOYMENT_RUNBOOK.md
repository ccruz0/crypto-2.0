# PROD Swap Deployment Runbook

## 1. Purpose

This runbook adds a small swap file (default 2 GB) on the PROD EC2 instance to improve resilience when memory is tight. After the **2026-03-11 PROD incident**, we confirmed the failure was instance-level (EC2 reachability, SSM, then app unreachable); memory was observed as tight with no swap. Adding swap is a **safety margin** so short memory spikes are less likely to trigger OOM or unresponsive behavior. It does not replace EC2 auto-recovery or proper sizing. See **docs/PROD_INCIDENT_2026-03-11_RECOVERY.md** for the incident summary and recommendations.

---

## 2. Preconditions

- **PROD must be reachable** via SSM or SSH.
- **Operator must have sudo access** on the PROD instance.
- **Repo on PROD** lives at **`/home/ubuntu/crypto-2.0`**. If you connect via **SSM Session Manager**, you may be `ssm-user`; use the full path or `sudo -u ubuntu -i` before `cd ~/...`.
- **Repo on PROD must be updated** (e.g. `git pull` in the repo root) so that the folder `infra/aws/prod_swap` and the script `setup_swap.sh` exist. If the folder does not exist yet, run the "Update repo on PROD" step first.

---

## 3. Deployment Steps

### Connect to PROD

**SSM:**

```bash
aws ssm start-session --target i-087953603011543c5 --region ap-southeast-1
```

**SSH (if key and host are known):**

```bash
ssh -i "atp-rebuild-2026.pem" ubuntu@ec2-52-220-32-147.ap-southeast-1.compute.amazonaws.com
```

(Replace hostname with the current PROD instance public DNS or IP if different.)

### Update repo on PROD

If `infra/aws/prod_swap` does not exist on the instance, update the repo first. Use the full path (SSM starts as `ssm-user`; repo is under ubuntu's home):

```bash
cd /home/ubuntu/crypto-2.0
git pull
ls infra/aws/prod_swap
```

Confirm that `setup_swap.sh` (and optionally `README.md`) are listed.

### Run swap setup

```bash
cd /home/ubuntu/crypto-2.0/infra/aws/prod_swap
sudo ./setup_swap.sh
```

If swap is already enabled, the script exits successfully without making changes.

---

## 4. Verification

Run these commands on PROD:

```bash
swapon --show
free -h
grep swapfile /etc/fstab
```

**Expected result:**

- **swapon --show:** `/swapfile` listed with type `file` and size ~2G (e.g. `2G`).
- **free -h:** Swap row shows non-zero Total (e.g. `2.0Gi`) and Free.
- **grep swapfile /etc/fstab:** One line: `/swapfile none swap sw 0 0`.

---

## 5. Optional Swappiness

To use swap only as a safety buffer (prefer RAM first), set swappiness to 10:

```bash
echo "vm.swappiness=10" | sudo tee /etc/sysctl.d/99-atp-swappiness.conf
sudo sysctl -p /etc/sysctl.d/99-atp-swappiness.conf
cat /proc/sys/vm/swappiness
```

**Expected value:** `10`.

---

## 6. Final Health Check

Confirm the stack is still healthy after swap deployment:

```bash
free -h
docker ps
systemctl is-active nginx
systemctl is-active snap.amazon-ssm-agent.amazon-ssm-agent
curl -sS https://dashboard.hilovivo.com/api/health
```

**Expected result:**

- **free -h:** Swap row shows 2G total; memory summary unchanged from before.
- **docker ps:** Containers (backend, db, market-updater, etc.) still running.
- **nginx:** `active`.
- **snap.amazon-ssm-agent.amazon-ssm-agent:** `active`.
- **curl:** HTTP 200 and a healthy JSON response (e.g. `{"status":"ok","path":"/api/health"}`).

---

## 7. Rollback

To remove swap and the swappiness override:

```bash
sudo swapoff /swapfile
sudo rm -f /swapfile
sudo sed -i '\|^/swapfile none swap sw 0 0$|d' /etc/fstab
sudo rm -f /etc/sysctl.d/99-atp-swappiness.conf
sudo sysctl vm.swappiness=60
```

Confirm with `swapon --show` (no output) and `free -h` (Swap 0).

---

## 8. Notes

- **Safety margin only:** Swap reduces fragility from short memory spikes; it is not a substitute for proper instance sizing or workload optimization.
- **Does not replace EC2 auto-recovery:** AWS-level recovery (CloudWatch alarm + EC2 recover action) remains the first line of defense for instance-level failures. See **infra/aws/ec2_auto_recovery_prod/**.
- **Next phase:** Add **observability** (e.g. MemAvailable, swap usage, OOM detection, docker daemon health) as signals only — not more restart or remediation scripts. Prefer consolidation of existing health/alert mechanisms over proliferation. See **docs/PROD_MEMORY_HARDENING.md** and **docs/ATP_RUNTIME_HEALTH_RECOVERY_BASELINE.md**.

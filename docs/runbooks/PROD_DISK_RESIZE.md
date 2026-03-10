# PROD: Increase disk size (EBS resize)

When the production instance runs out of disk (e.g. ATP health alerts with `verify_label: FAIL:DISK:...`, or "no space left on device"), increase the root EBS volume and extend the filesystem on the instance.

- **Instance PROD:** `i-087953603011543c5` (atp-rebuild-2026)
- **Region:** `ap-southeast-1`

---

## 1. Optional: check current usage

From your machine (SSM) or on the instance:

```bash
# Via SSM from your machine
aws ssm send-command \
  --instance-ids i-087953603011543c5 \
  --document-name "AWS-RunShellScript" \
  --parameters 'commands=["df -h /","docker system df","lsblk"]' \
  --region ap-southeast-1 \
  --query 'Command.CommandId' --output text
# Then: aws ssm get-command-invocation --command-id <ID> --instance-id i-087953603011543c5 --region ap-southeast-1
```

Or on the instance (SSH or SSM session):

```bash
df -h /
docker system df
lsblk
```

---

## 2. Increase EBS volume size (AWS Console)

1. **EC2 → Volumes** (region **ap-southeast-1**).
2. Find the volume attached to instance **i-087953603011543c5** (e.g. 8 GiB or 20 GiB).
3. Select the volume → **Actions → Modify volume**.
4. Set **Size** to the new value (e.g. **30 GiB** or **40 GiB**) → **Modify**.
5. Wait until the volume status is **completed** (usually under a minute).

---

## 3. Extend partition and filesystem (on PROD instance)

Connect to the instance via **SSM**, **SSH**, or **EC2 Serial Console** (if SSM/SSH are unavailable — see [docs/aws/PROD_ACCESS_WHEN_SSM_AND_SSH_FAIL.md](../aws/PROD_ACCESS_WHEN_SSM_AND_SSH_FAIL.md)):

```bash
# SSM
aws ssm start-session --target i-087953603011543c5 --region ap-southeast-1
```

Then on the instance (device names may be `nvme0n1`/`nvme0n1p1` or `xvda`/`xvda1`):

```bash
# See root block device and partition (e.g. /dev/nvme0n1, partition 1)
lsblk

# Grow the partition (use the device and partition number from lsblk; common: nvme0n1 1)
sudo growpart /dev/nvme0n1 1
# If your root is on xvda: sudo growpart /dev/xvda 1

# Resize the filesystem (use the partition from lsblk, e.g. nvme0n1p1 or xvda1)
sudo resize2fs /dev/nvme0n1p1
# If root is xvda1: sudo resize2fs /dev/xvda1

# Confirm
df -h /
```

If `growpart` or `resize2fs` are missing (e.g. minimal AMI):

```bash
sudo apt-get update && sudo apt-get install -y cloud-guest-utils
```

---

## 4. Optional: free space without resizing

If you only need temporary relief:

- **Docker:** `docker system prune -a -f` (removes unused images/containers).
- **Logs:** `sudo journalctl --vacuum-time=3d`; clear old logs in `/var/log` (or use `infra/cleanup_disk.sh` if installed).
- **APT:** `sudo apt-get clean`.

For a lasting fix, prefer increasing the EBS volume (steps 2 and 3).

---

## Reference

- LAB disk resize (same steps, different instance): [LAB_DISK_RESIZE_OPENCLAW_REDEPLOY.md](LAB_DISK_RESIZE_OPENCLAW_REDEPLOY.md).
- Daily disk cleanup script: `infra/cleanup_disk.sh` (install via `infra/install_cleanup_cron.sh`).

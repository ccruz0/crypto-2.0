# LAB: Expand EBS root volume (OpenClaw / Docker “no space left on device”)

## Root cause (confirmed)

OpenClaw on LAB is deployed with Docker. Image pull/extract failed with **`no space left on device`** because the **LAB root volume was nearly full** (~**96%** used on ~**38 GiB**). Docker layer extraction needs contiguous free space on `/`; shrinking images is **not** the primary fix when **backend** and **postgres** containers legitimately hold the disk.

**Primary fix:** grow the **EBS root volume**, then **grow the partition and filesystem** inside Ubuntu **24.04**, then re-run **OpenClaw repair via SSM** and validate from **LAB** and **PROD**.

**References**

- LAB instance (typical): `i-0d82c172235770a0d` (atp-lab-ssm-clean), private IP e.g. `172.31.3.214`
- Region (typical): `ap-southeast-1`
- Repair script: `scripts/openclaw/repair_openclaw_lab_via_ssm.sh`
- On-instance repair: `scripts/openclaw/repair_openclaw_lab_on_instance.sh`

---

## 0. Before (validation — capture baseline)

### From your laptop (SSM Run Command — no interactive shell required)

```bash
export AWS_REGION="${AWS_REGION:-ap-southeast-1}"
export LAB_INSTANCE_ID="${LAB_INSTANCE_ID:-i-0d82c172235770a0d}"

CID=$(aws ssm send-command \
  --instance-ids "$LAB_INSTANCE_ID" \
  --region "$AWS_REGION" \
  --document-name "AWS-RunShellScript" \
  --timeout-seconds 120 \
  --parameters 'commands=["bash -lc \"echo === df ===; df -h /; echo === lsblk ===; lsblk -f; echo === root mount ===; findmnt -n -o SOURCE,FSTYPE /; echo === docker df ===; docker system df 2>/dev/null || true\""]' \
  --query 'Command.CommandId' --output text)

# Wait ~15s, then:
aws ssm get-command-invocation \
  --command-id "$CID" \
  --instance-id "$LAB_INSTANCE_ID" \
  --region "$AWS_REGION" \
  --query '[Status,StandardOutputContent,StandardErrorContent]' --output text
```

**Record:** `Use%` on `/`, `findmnt` device, and `FSTYPE` (**ext4** vs **xfs**).

### Optional — PROD reachability to LAB (expects failure if OpenClaw is down)

```bash
export DASHBOARD_INSTANCE_ID="${DASHBOARD_INSTANCE_ID:-i-087953603011543c5}"
export LAB_IP="${LAB_PRIVATE_IP:-172.31.3.214}"

CID=$(aws ssm send-command \
  --instance-ids "$DASHBOARD_INSTANCE_ID" \
  --region "$AWS_REGION" \
  --document-name "AWS-RunShellScript" \
  --parameters "commands=[\"curl -sS -I --max-time 5 http://${LAB_IP}:8080/ 2>&1 | head -20 || true\"]" \
  --query 'Command.CommandId' --output text)

aws ssm get-command-invocation \
  --command-id "$CID" \
  --instance-id "$DASHBOARD_INSTANCE_ID" \
  --region "$AWS_REGION" \
  --query '[Status,StandardOutputContent]' --output text
```

---

## 1. Expand the EBS root volume (AWS)

### 1a. Find the root volume ID

**Console:** EC2 → **Instances** → select LAB → **Storage** tab → note **Volume ID** of the root device (e.g. `/dev/sda1` / `/dev/xvda` mapping).

**CLI:**

```bash
export AWS_REGION="${AWS_REGION:-ap-southeast-1}"
export LAB_INSTANCE_ID="${LAB_INSTANCE_ID:-i-0d82c172235770a0d}"

aws ec2 describe-instances --region "$AWS_REGION" --instance-ids "$LAB_INSTANCE_ID" \
  --query 'Reservations[0].Instances[0].BlockDeviceMappings[*].{Device:DeviceName,VolumeId:Ebs.VolumeId}' --output table
```

Pick the **root** row (often **`/dev/sda1`** or **`/dev/xvda`** on the API; Nitro guests still map correctly). Then:

```bash
export ROOT_VOL="vol-xxxxxxxx"   # from table

aws ec2 describe-volumes --region "$AWS_REGION" --volume-ids "$ROOT_VOL" \
  --query 'Volumes[0].{Size:Size,State:State,Az:AvailabilityZone}' --output table
```

### 1b. (Recommended) Snapshot for rollback

**Console:** EC2 → **Volumes** → select volume → **Actions** → **Create snapshot** → name e.g. `lab-root-pre-openclaw-resize-YYYYMMDD`.

**CLI:**

```bash
aws ec2 create-snapshot \
  --region "$AWS_REGION" \
  --volume-id "$ROOT_VOL" \
  --description "LAB root before expand for OpenClaw"
```

**Rollback note:** restoring from snapshot means **replace/reattach volume or AMI restore** — not instant “undo.” For a routine grow, snapshot is **disaster rollback**, not a one-click revert.

### 1c. Modify volume size

Pick a size with headroom for Docker layers and future updates (e.g. **64–80 GiB** if you were at 38 GiB).

**Console:** EC2 → **Volumes** → select root volume → **Actions** → **Modify volume** → set **Size** → **Modify** → confirm.

**CLI:**

```bash
export NEW_SIZE_GIB=80   # adjust

aws ec2 modify-volume \
  --region "$AWS_REGION" \
  --volume-id "$ROOT_VOL" \
  --size "$NEW_SIZE_GIB"

aws ec2 describe-volumes-modifications \
  --region "$AWS_REGION" \
  --volume-ids "$ROOT_VOL" \
  --query 'VolumesModifications[0].{State:ModificationState,Progress:Progress}' --output table
```

Wait until modification state is **`completed`** (poll every 10–30s).

**Risk note:** EBS **grow is forward-only**; you cannot shrink the volume in place. Oversizing slightly (e.g. 80 GiB) is normal.

---

## 2. Grow partition and filesystem inside LAB (Ubuntu 24.04)

No need to reboot for a standard single-partition root on a Nitro instance, once AWS shows the larger volume.

### 2a. Recommended: repo script over SSM (detects ext4 vs xfs)

The repo ships **`scripts/aws/lab_grow_root_filesystem.sh`**, which uses **`lsblk`** (`PKNAME`, `PARTNUM`), **`growpart`**, then **`resize2fs`** (ext4) or **`xfs_growfs /`** (xfs).

**If LAB already has an up-to-date clone** of this repo:

```bash
export AWS_REGION="${AWS_REGION:-ap-southeast-1}"
export LAB_INSTANCE_ID="${LAB_INSTANCE_ID:-i-0d82c172235770a0d}"
REPO="/home/ubuntu/crypto-2.0"

CID=$(aws ssm send-command \
  --instance-ids "$LAB_INSTANCE_ID" \
  --region "$AWS_REGION" \
  --document-name "AWS-RunShellScript" \
  --timeout-seconds 300 \
  --parameters "commands=[\"bash -lc 'set -euo pipefail; cd $REPO && git fetch origin main && git checkout main && git pull origin main || true; bash $REPO/scripts/aws/lab_grow_root_filesystem.sh'\"]" \
  --query 'Command.CommandId' --output text)

sleep 25
aws ssm get-command-invocation \
  --command-id "$CID" \
  --instance-id "$LAB_INSTANCE_ID" \
  --region "$AWS_REGION" \
  --query '[Status,StandardOutputContent,StandardErrorContent]' --output text
```

**If the script is missing on LAB** (chicken-and-egg before merge): copy `scripts/aws/lab_grow_root_filesystem.sh` to the instance once (paste, S3, or merge + pull), or use the manual commands in **2b**.

### 2b. Manual (interactive SSM session or console serial)

```bash
aws ssm start-session --target "$LAB_INSTANCE_ID" --region "$AWS_REGION"
```

```bash
sudo apt-get update && sudo apt-get install -y cloud-guest-utils
df -h /
lsblk -f
findmnt -n -o SOURCE,FSTYPE /
```

Typical Nitro root: **`/dev/nvme0n1p1`** (disk **`/dev/nvme0n1`**, partition **`1`**):

```bash
sudo growpart /dev/nvme0n1 1
```

Then, using **`findmnt -n -o FSTYPE /`**:

| FSTYPE | Command |
|--------|---------|
| **ext4** | `sudo resize2fs "$(findmnt -n -o SOURCE /)"` |
| **xfs** | `sudo xfs_growfs /` |

**LVM:** If `lsblk` shows logical volumes (e.g. `ubuntu--vg-ubuntu--lv`) as the root mount source, **do not** use `growpart` on that path; use **`pvresize`**, **`lvextend -l +100%FREE`**, then **`resize2fs`** or **`xfs_growfs`** on the LV (different procedure).

---

## 3. After disk grow (validation)

```bash
CID=$(aws ssm send-command \
  --instance-ids "$LAB_INSTANCE_ID" \
  --region "$AWS_REGION" \
  --document-name "AWS-RunShellScript" \
  --parameters 'commands=["bash -lc \"df -h /; docker info >/dev/null && echo docker_ok\""]' \
  --query 'Command.CommandId' --output text)

sleep 12
aws ssm get-command-invocation \
  --command-id "$CID" \
  --instance-id "$LAB_INSTANCE_ID" \
  --region "$AWS_REGION" \
  --query 'StandardOutputContent' --output text
```

**Pass criteria:** `df -h /` shows the **new size** (or very close) and **Use%** well below the prior ~96%.

---

## 4. Re-run OpenClaw repair (SSM)

From repo root on your laptop (after this runbook’s scripts are on `main` on LAB, or use embed):

```bash
cd /path/to/automated-trading-platform

# Normal (script already on LAB after git pull on instance — wrapper can pull if you omit SKIP_GIT_PULL)
./scripts/openclaw/repair_openclaw_lab_via_ssm.sh

# Or bootstrap the repair script from your laptop without relying on LAB git:
OPENCLAW_SSM_EMBED_REPAIR=1 SKIP_GIT_PULL=1 ./scripts/openclaw/repair_openclaw_lab_via_ssm.sh
```

**Do not** rely on deleting **active** images used by backend/postgres; EBS expansion is the intended fix.

---

## 5. Post-fix validation

### 5a. LAB — listener and local HTTP

```bash
CID=$(aws ssm send-command \
  --instance-ids "$LAB_INSTANCE_ID" \
  --region "$AWS_REGION" \
  --document-name "AWS-RunShellScript" \
  --parameters 'commands=["bash -lc \"ss -lntp | grep -E \":8080\\\\b\" || true; curl -sS -I --max-time 8 http://127.0.0.1:8080/ | head -20\""]' \
  --query 'Command.CommandId' --output text)

sleep 15
aws ssm get-command-invocation \
  --command-id "$CID" \
  --instance-id "$LAB_INSTANCE_ID" \
  --region "$AWS_REGION" \
  --query 'StandardOutputContent' --output text
```

**Pass criteria:** `LISTEN` on **8080** and `curl` returns HTTP status line (e.g. **401** / **200** / **302**).

### 5b. PROD — reach LAB private IP:8080

```bash
CID=$(aws ssm send-command \
  --instance-ids "$DASHBOARD_INSTANCE_ID" \
  --region "$AWS_REGION" \
  --document-name "AWS-RunShellScript" \
  --parameters "commands=[\"curl -sS -I --max-time 5 http://${LAB_IP}:8080/ 2>&1 | head -25\"]" \
  --query 'Command.CommandId' --output text)

sleep 12
aws ssm get-command-invocation \
  --command-id "$CID" \
  --instance-id "$DASHBOARD_INSTANCE_ID" \
  --region "$AWS_REGION" \
  --query 'StandardOutputContent' --output text
```

**If LAB curl works but PROD curl times out:** networking — allow **inbound TCP 8080** on the **LAB security group** from the **PROD instance private IP** or **PROD security group**; confirm same-VPC routing.

**Optional public check:** `curl -I --max-time 10 https://dashboard.hilovivo.com/openclaw/` (expect **401** with Basic Auth if configured).

---

## 6. Rollback / risks (short)

| Item | Note |
|------|------|
| **EBS shrink** | Not supported in place; choose size deliberately. |
| **Snapshot** | Recommended before modify; restore is a **separate** DR procedure, not automatic rollback. |
| **growpart / resize** | Wrong device/partition can harm data — always confirm `findmnt` / `lsblk` first. |
| **LVM** | Default Ubuntu EC2 AMIs are usually **single partition + ext4**; if you use LVM, use LVM grow steps instead of this snippet. |

---

## Related

- Older note (partially superseded): `docs/runbooks/LAB_DISK_RESIZE_OPENCLAW_REDEPLOY.md`
- Nginx / private IP: `docs/runbooks/NGINX_OPENCLAW_PROXY_TO_LAB_PRIVATE_IP.md`

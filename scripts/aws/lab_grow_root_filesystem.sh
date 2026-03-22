#!/usr/bin/env bash
# Grow EBS root partition + filesystem on Ubuntu EC2 after volume modify (no reboot).
# Run as root on LAB (e.g. AWS SSM Run Command). See docs/runbooks/LAB_EBS_ROOT_EXPAND_OPENCLAW.md
set -euo pipefail

echo "=== before ==="
df -h /
findmnt -n -o SOURCE,FSTYPE /
lsblk -f

ROOT_DEV="$(findmnt -n -o SOURCE /)"
echo "ROOT_DEV=$ROOT_DEV"

PK="$(lsblk -ndo PKNAME "$ROOT_DEV" 2>/dev/null || true)"
PN="$(lsblk -ndo PARTNUM "$ROOT_DEV" 2>/dev/null || true)"

if [[ -z "$PK" || -z "$PN" ]]; then
  echo "Could not get parent disk (PKNAME) or PARTNUM for $ROOT_DEV."
  echo "If root is on LVM, use pvresize/lvextend instead of this script."
  exit 1
fi

DISK="/dev/$PK"
echo "DISK=$DISK PARTNUM=$PN"

export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq cloud-guest-utils

growpart "$DISK" "$PN"

FS="$(findmnt -n -o FSTYPE /)"
echo "FSTYPE=$FS"

case "$FS" in
  ext4) resize2fs "$ROOT_DEV" ;;
  xfs) xfs_growfs / ;;
  *)
    echo "Unsupported root filesystem type: $FS (expected ext4 or xfs)"
    exit 1
    ;;
esac

echo "=== after ==="
df -h /
lsblk -f

#!/bin/bash
# Daily disk cleanup for the ATP server.
# Installed as a cron job by infra/install_cleanup_cron.sh (runs at 2 AM).
# Safe to run anytime — does NOT remove named Docker volumes (postgres, grafana, etc.)
# and does NOT restart containers.
set -e

BEFORE=$(df -P / | awk 'NR==2 {print $5}')
echo "=== ATP disk cleanup: $(date -Is) ==="
echo "Disk before: $BEFORE"

# 1. Dangling images (untagged leftovers from builds)
echo "Pruning dangling images..."
docker image prune -f 2>/dev/null || true

# 2. Unused images older than 48h (keeps images for the running stack)
echo "Pruning unused images >48h..."
docker image prune -af --filter "until=48h" 2>/dev/null || true

# 3. Build cache older than 24h
echo "Pruning build cache >24h..."
docker builder prune -af --filter "until=24h" 2>/dev/null || true

# 4. Stopped containers and unused networks (NOT volumes — keeps DB data safe)
echo "Pruning stopped containers and unused networks..."
docker container prune -f 2>/dev/null || true
docker network prune -f 2>/dev/null || true

# 5. Truncate Docker container logs (daemon log-rotation handles future growth)
echo "Truncating container logs..."
sudo find /var/lib/docker/containers/ -name "*-json.log" -type f \
  -exec truncate -s 0 {} \; 2>/dev/null || true

# 6. Journal logs — keep 5 days
echo "Vacuuming journal logs (keep 5d)..."
sudo journalctl --vacuum-time=5d 2>/dev/null || true

# 7. Application log files
if [ -d ~/automated-trading-platform ]; then
  echo "Cleaning app logs (>5MB or >5 days)..."
  find ~/automated-trading-platform -maxdepth 4 -type f -name "*.log" -size +5M -delete 2>/dev/null || true
  find ~/automated-trading-platform -maxdepth 4 -type f -name "*.log" -mtime +5 -delete 2>/dev/null || true
fi

# 8. apt cache
echo "Cleaning apt cache..."
sudo apt-get clean 2>/dev/null || true

# 9. Temp files older than 5 days
echo "Cleaning temp files >5d..."
sudo find /tmp -type f -atime +5 -delete 2>/dev/null || true
sudo find /var/tmp -type f -atime +5 -delete 2>/dev/null || true

# 10. Old kernels (keep current + one previous)
OLD_KERNELS=$(dpkg -l 2>/dev/null | grep -E 'linux-image-[0-9]+' | grep -v "$(uname -r)" | awk '{print $2}' | head -n -1 || true)
if [ -n "$OLD_KERNELS" ]; then
  echo "Removing old kernels..."
  sudo apt-get purge -y $OLD_KERNELS 2>/dev/null || true
fi

AFTER=$(df -P / | awk 'NR==2 {print $5}')
echo "Disk after:  $AFTER"
echo "=== cleanup done ==="


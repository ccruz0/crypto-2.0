#!/bin/bash
# Disk cleanup script for automated trading platform server
# Run this script periodically to free up disk space

set -e

echo "🧹 Starting disk cleanup..."
echo "📊 Disk usage before cleanup:"
df -h / | tail -1

# 1. Clean Docker system (remove stopped containers, unused images, volumes, networks)
echo ""
echo "🐳 Cleaning Docker system..."
docker system prune -f --volumes

# 2. Remove old Docker images (older than 7 days)
echo ""
echo "🖼️  Removing old Docker images (>7 days)..."
docker image prune -af --filter "until=168h" || true

# 3. Remove dangling images
echo ""
echo "🗑️  Removing dangling images..."
docker image prune -f || true

# 4. Clean journal logs (keep last 7 days)
echo ""
echo "📝 Cleaning system journal logs (keeping last 7 days)..."
sudo journalctl --vacuum-time=7d 2>/dev/null || true

# 5. Clean application log files (remove logs >10MB and older than 7 days)
echo ""
echo "📋 Cleaning application logs..."
if [ -d ~/automated-trading-platform ]; then
    # Remove large log files (>10MB)
    find ~/automated-trading-platform -type f -name "*.log" -size +10M -delete 2>/dev/null || true
    
    # Remove old log files (>7 days)
    find ~/automated-trading-platform -type f -name "*.log" -mtime +7 -delete 2>/dev/null || true
fi

# 6. Clean Docker build cache
echo ""
echo "🧱 Cleaning Docker build cache..."
docker builder prune -af --filter "until=168h" || true

# 7. Clean apt cache
echo ""
echo "📦 Cleaning apt cache..."
sudo apt-get clean || true
sudo apt-get autoclean || true

# 8. Clean temporary files
echo ""
echo "🗂️  Cleaning temporary files..."
sudo find /tmp -type f -atime +7 -delete 2>/dev/null || true
sudo find /var/tmp -type f -atime +7 -delete 2>/dev/null || true

# 9. Clean old package lists
echo ""
echo "📚 Cleaning old package lists..."
sudo rm -rf /var/lib/apt/lists/* 2>/dev/null || true

# 10. Remove old kernels (keep current and one previous)
echo ""
echo "🔧 Cleaning old kernels..."
OLD_KERNELS=$(dpkg -l | grep -E 'linux-image-[0-9]+' | grep -v $(uname -r) | awk '{print $2}' | head -n -1)
if [ ! -z "$OLD_KERNELS" ]; then
    sudo apt-get purge -y $OLD_KERNELS 2>/dev/null || true
fi

echo ""
echo "✅ Disk cleanup completed!"
echo "📊 Disk usage after cleanup:"
df -h / | tail -1

# Show what was cleaned
echo ""
echo "📈 Space freed:"
DU_BEFORE=$(df / | tail -1 | awk '{print $3}')
# We can't easily measure before/after in one script run, so just show final status
echo "Current disk usage shown above."


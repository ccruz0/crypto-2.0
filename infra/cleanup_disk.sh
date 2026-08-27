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

# 2. Unused images: keep the N most recent tags per repo, regardless of age.
#
# El filtro anterior era "until=48h" y NO servia: con el auto-merge desplegando
# varias veces al dia, ninguna imagen llega a las 48h antes de que se acumulen
# las siguientes. El 27-ago-2026 la limpieza de las 02:00 recupero exactamente
# 0B con el disco al 90%, y a mediodia estaba al 92% con 3.9G libres.
# A ~1.4GB por imagen, la ventana de 48h nunca las alcanza.
#
# Nunca se borra una imagen usada por un contenedor en marcha.
KEEP_IMAGES="${KEEP_IMAGES:-3}"
echo "Pruning unused images (keeping $KEEP_IMAGES most recent per repo)..."
IN_USE=$(docker ps --format '{{.Image}}' | sort -u)
for REPO in $(docker images --format '{{.Repository}}' | grep -v '^<none>$' | sort -u); do
  for TAG in $(docker images "$REPO" --format '{{.Tag}}' | tail -n +$((KEEP_IMAGES + 1))); do
    [ "$TAG" = "<none>" ] && continue
    IMG="$REPO:$TAG"
    if echo "$IN_USE" | grep -qF "$IMG"; then continue; fi
    echo "  rmi $IMG"
    docker rmi "$IMG" >/dev/null 2>&1 || true
  done
done

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

# 7. Application log files (PROD may use automated-trading-platform or crypto-2.0 clone path)
for _app_root in "$HOME/automated-trading-platform" "$HOME/crypto-2.0"; do
  if [ -d "$_app_root" ]; then
    echo "Cleaning app logs in $_app_root (>5MB or >5 days)..."
    find "$_app_root" -maxdepth 4 -type f -name "*.log" -size +5M -delete 2>/dev/null || true
    find "$_app_root" -maxdepth 4 -type f -name "*.log" -mtime +5 -delete 2>/dev/null || true
  fi
done

# 7b. npm caches (se regeneran solas; sumaban 1.75GB el 27-ago-2026)
for _c in "$HOME/.npm/_cacache" /root/.npm/_cacache; do
  [ -d "$_c" ] && { echo "Cleaning npm cache $_c..."; sudo rm -rf "$_c" 2>/dev/null || true; }
done

# 8. apt cache
echo "Cleaning apt cache..."
sudo apt-get clean 2>/dev/null || true

# 9. Temp files older than 5 days
echo "Cleaning temp files >5d..."
sudo find /tmp -type f -atime +5 -delete 2>/dev/null || true
# Directorios de trabajo abandonados (clones de git de automatismos viejos).
# El -type f de arriba vacia los ficheros pero deja los directorios y, si algo
# los ha leido, -atime no casa nunca. Se van por fecha de modificacion.
sudo find /tmp -mindepth 1 -maxdepth 1 -type d -mtime +2 -exec rm -rf {} + 2>/dev/null || true
sudo find /var/tmp -type f -atime +5 -delete 2>/dev/null || true

# 9b. Stale Jarvis coding-workflow sandboxes in /tmp (each can be hundreds of MB
# of node_modules). These are transient build dirs; nothing else reclaims them.
# Remove sandboxes whose contents have not been modified recently so an
# in-progress workflow is never disturbed.
JARVIS_SANDBOX_DIR="${JARVIS_SANDBOX_DIR:-/tmp/jarvis-sandbox}"
JARVIS_SANDBOX_KEEP_MIN="${JARVIS_SANDBOX_KEEP_MIN:-720}"  # default: keep last 12h
if [ -d "$JARVIS_SANDBOX_DIR" ]; then
  echo "Cleaning stale Jarvis sandboxes in $JARVIS_SANDBOX_DIR (idle >${JARVIS_SANDBOX_KEEP_MIN}m)..."
  sudo find "$JARVIS_SANDBOX_DIR" -mindepth 1 -maxdepth 1 -type d \
    -mmin +"$JARVIS_SANDBOX_KEEP_MIN" -exec rm -rf {} + 2>/dev/null || true
fi

# 10. Old kernels (keep current + one previous)
OLD_KERNELS=$(dpkg -l 2>/dev/null | grep -E 'linux-image-[0-9]+' | grep -v "$(uname -r)" | awk '{print $2}' | head -n -1 || true)
if [ -n "$OLD_KERNELS" ]; then
  echo "Removing old kernels..."
  sudo apt-get purge -y $OLD_KERNELS 2>/dev/null || true
fi

AFTER=$(df -P / | awk 'NR==2 {print $5}')
echo "Disk after:  $AFTER"
echo "=== cleanup done ==="


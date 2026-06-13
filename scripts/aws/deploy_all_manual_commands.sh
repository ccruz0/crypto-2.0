#!/usr/bin/env bash
# Print commands to run ON THE EC2 SERVER (SSH or EC2 Instance Connect) when SSM is unreachable.
# Usage: ./scripts/aws/deploy_all_manual_commands.sh
# Then: EC2 Console → Instance → Connect → EC2 Instance Connect (or SSH), paste the block below.

set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$REPO_ROOT"

cat << 'MANUAL_EOF'
# ========== Run these commands ON THE EC2 SERVER (paste in EC2 Instance Connect or SSH) ==========

REPO=/home/ubuntu/crypto-2.0
test -d "$REPO/.git" || { echo "❌ No project dir"; exit 1; }

# 1) Pull monorepo as ubuntu (SSM runs as root; GitHub SSH key is for ubuntu)
sudo -u ubuntu git -C "$REPO" fetch origin main
sudo -u ubuntu git -C "$REPO" pull --ff-only origin main
sudo -u ubuntu bash -lc "cd $REPO && git rev-parse --short HEAD"
# Remove stale nested frontend git repo if a legacy deploy left one behind
if [ -d "$REPO/frontend/.git" ]; then
  sudo rm -rf "$REPO/frontend/.git" || rm -rf "$REPO/frontend/.git"
  sudo -u ubuntu git -C "$REPO" checkout HEAD -- frontend/
fi
sudo -u ubuntu bash -lc "cd $REPO && bash scripts/verify_no_external_frontend_deploy.sh --runtime"

# 2) Render secrets (needs AWS CLI on the instance)
cd "$REPO"
bash scripts/aws/render_runtime_env.sh || true

# 3) Rebuild and start all services
sudo -u ubuntu bash -lc "cd $REPO && bash scripts/verify_clean_worktree.sh --frontend-only"
docker compose --profile aws down || true
docker compose --profile aws build --no-cache
docker image prune -f || true
docker compose --profile aws up -d --build

# 4) Wait for backend, restart nginx
sleep 30
for i in $(seq 1 20); do curl -sf --connect-timeout 5 http://localhost:8002/ping_fast >/dev/null 2>&1 && echo "✅ Backend healthy" && break || echo "⏳ $i/20"; sleep 10; done
sudo systemctl restart nginx || true
docker compose --profile aws ps

echo "✅ Manual deploy completed"

# ========== End of commands ==========
MANUAL_EOF

echo ""
echo "Tip: EC2 Console → select instance i-087953603011543c5 → Connect → EC2 Instance Connect → paste the block above."

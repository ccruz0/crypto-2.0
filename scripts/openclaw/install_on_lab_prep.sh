#!/usr/bin/env bash
# Steps 1-3 only: apt HTTPS, Docker+git, clone repo. Run on LAB via SSM; then store PAT and run install_on_lab.sh.
set -e
REPO_DIR="${REPO_DIR:-/home/ubuntu/crypto-2.0}"
GIT_REPO_URL="${GIT_REPO_URL:-https://github.com/ccruz0/crypto-2.0.git}"

echo "=== 1) Apt over HTTPS ==="
sudo sed -i.bak 's|http://ap-southeast-1.ec2.archive.ubuntu.com|https://ap-southeast-1.ec2.archive.ubuntu.com|g' /etc/apt/sources.list 2>/dev/null || true
sudo sed -i 's|http://security.ubuntu.com|https://security.ubuntu.com|g' /etc/apt/sources.list 2>/dev/null || true
sudo sed -i 's|http://archive.ubuntu.com|https://archive.ubuntu.com|g' /etc/apt/sources.list 2>/dev/null || true
sudo apt update -qq || true
sudo apt install -y -qq apt-transport-https ca-certificates 2>/dev/null || true
sudo apt update -qq

echo "=== 2) Docker + Git ==="
sudo apt install -y docker.io docker-compose-v2 git
sudo usermod -aG docker "$(whoami)" 2>/dev/null || true

echo "=== 3) Repo ==="
if [ ! -d "$REPO_DIR/.git" ]; then
  sudo mkdir -p "$(dirname "$REPO_DIR")"
  sudo chown "$(whoami):$(whoami)" "$(dirname "$REPO_DIR")" 2>/dev/null || true
  git clone "$GIT_REPO_URL" "$REPO_DIR"
fi
cd "$REPO_DIR"
git fetch origin main 2>/dev/null || true
git checkout main 2>/dev/null || true

echo "DONE. Run full install with token: store PAT in SSM param /openclaw/lab/github_pat then re-run install."

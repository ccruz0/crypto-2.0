#!/usr/bin/env bash
# Run this ON the EC2 instance (e.g. after ssh ubuntu@...)
# Prompts for Exchange API Key and Secret, appends them to secrets/runtime.env,
# fixes perms, and tells you to restart the backend.
# Usage: cd /home/ubuntu/automated-trading-platform && bash scripts/ec2_add_exchange_credentials.sh

set -e
REPO_DIR="${REPO_DIR:-/home/ubuntu/automated-trading-platform}"
ENV_FILE="${REPO_DIR}/secrets/runtime.env"

echo "Add Exchange API credentials to secrets/runtime.env"
echo ""

read -r -p "Exchange API Key: " API_KEY
read -rs -p "Exchange API Secret: " API_SECRET
echo ""

if [[ -z "$API_KEY" || -z "$API_SECRET" ]]; then
  echo "Error: API Key and Secret are required." >&2
  exit 1
fi

# Remove old lines if present
if [[ -f "$ENV_FILE" ]]; then
  sudo sed -i.bak '/^EXCHANGE_CUSTOM_API_KEY=/d' "$ENV_FILE"
  sudo sed -i '/^EXCHANGE_CUSTOM_API_SECRET=/d' "$ENV_FILE"
fi

# Append new lines (use sudo to write)
echo "EXCHANGE_CUSTOM_API_KEY=$API_KEY" | sudo tee -a "$ENV_FILE" > /dev/null
echo "EXCHANGE_CUSTOM_API_SECRET=$API_SECRET" | sudo tee -a "$ENV_FILE" > /dev/null

# So backend container (appuser 10001) can read the file
sudo chown 10001:10001 "$ENV_FILE"
sudo chmod 600 "$ENV_FILE"

echo ""
echo "Done. Restart the backend so it picks up the new env:"
echo "  sudo docker compose --profile aws up -d --force-recreate backend-aws"
echo ""

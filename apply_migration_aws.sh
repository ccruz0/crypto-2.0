#!/bin/bash
# Quick script to apply migration to AWS database
# This can be run manually if sync_to_aws.sh fails

set -e

# Try to use SSH alias first, fallback to IP
EC2_HOST_SSH="hilovivo-aws"
EC2_HOST_IP="175.41.189.249"
EC2_USER="ubuntu"

# Unified SSH
. ./scripts/ssh_key.sh 2>/dev/null || source ./scripts/ssh_key.sh

# Determine which host to use
EC2_HOST=""
if ssh -o ConnectTimeout=5 -o StrictHostKeyChecking=no "$EC2_HOST_SSH" "echo 'Connected'" > /dev/null 2>&1; then
  EC2_HOST="$EC2_HOST_SSH"
  echo "✅ Using SSH alias: $EC2_HOST"
elif ssh -o ConnectTimeout=5 -o StrictHostKeyChecking=no "$EC2_USER@$EC2_HOST_IP" "echo 'Connected'" > /dev/null 2>&1; then
  EC2_HOST="$EC2_USER@$EC2_HOST_IP"
  echo "✅ Using IP: $EC2_HOST_IP"
else
  echo "❌ Cannot connect to AWS instance"
  echo "   Tried: $EC2_HOST_SSH and $EC2_HOST_IP"
  exit 1
fi

echo "🔄 Applying database migration to AWS..."

if [[ "$EC2_HOST" == "hilovivo-aws" ]]; then
  ssh -o StrictHostKeyChecking=no $EC2_HOST << 'MIGRATION_SCRIPT'
cd ~/automated-trading-platform

echo "Applying previous_price migration..."
docker compose exec -T backend python backend/scripts/apply_migration_previous_price.py || {
    echo "⚠️  Migration script failed, trying direct SQL..."
    docker compose exec -T db psql -U trader -d atp -c "ALTER TABLE signal_throttle_states ADD COLUMN IF NOT EXISTS previous_price DOUBLE PRECISION NULL;" || echo "Migration may have already been applied"
}

echo "✅ Migration complete!"
MIGRATION_SCRIPT
else
  ssh_cmd "$EC2_HOST" << 'MIGRATION_SCRIPT'
cd ~/automated-trading-platform

echo "Applying previous_price migration..."
docker compose exec -T backend python backend/scripts/apply_migration_previous_price.py || {
    echo "⚠️  Migration script failed, trying direct SQL..."
    docker compose exec -T db psql -U trader -d atp -c "ALTER TABLE signal_throttle_states ADD COLUMN IF NOT EXISTS previous_price DOUBLE PRECISION NULL;" || echo "Migration may have already been applied"
}

echo "✅ Migration complete!"
MIGRATION_SCRIPT
fi

echo "✅ Migration applied successfully!"


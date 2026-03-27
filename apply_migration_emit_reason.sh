#!/bin/bash
# Quick script to apply emit_reason migration to AWS database

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

echo "🔄 Applying emit_reason migration to AWS..."

if [[ "$EC2_HOST" == "hilovivo-aws" ]]; then
  ssh -o StrictHostKeyChecking=no $EC2_HOST << 'MIGRATION_SCRIPT'
cd ~/crypto-2.0

echo "Applying emit_reason migration..."
docker compose exec -T backend python backend/scripts/apply_migration_emit_reason.py || {
    echo "⚠️  Migration script failed, trying direct SQL..."
    docker compose exec -T db psql -U trader -d atp -c "ALTER TABLE signal_throttle_states ADD COLUMN IF NOT EXISTS emit_reason VARCHAR(500) NULL;" || echo "Migration may have already been applied"
}

echo "✅ Migration complete!"
MIGRATION_SCRIPT
else
  ssh_cmd "$EC2_HOST" << 'MIGRATION_SCRIPT'
cd ~/crypto-2.0

echo "Applying emit_reason migration..."
docker compose exec -T backend python backend/scripts/apply_migration_emit_reason.py || {
    echo "⚠️  Migration script failed, trying direct SQL..."
    docker compose exec -T db psql -U trader -d atp -c "ALTER TABLE signal_throttle_states ADD COLUMN IF NOT EXISTS emit_reason VARCHAR(500) NULL;" || echo "Migration may have already been applied"
}

echo "✅ Migration complete!"
MIGRATION_SCRIPT
fi

echo "✅ Migration applied successfully!"


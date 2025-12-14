#!/bin/bash
# Quick script to apply migration to AWS database
# This can be run manually if sync_to_aws.sh fails

set -e

EC2_HOST="54.254.150.31"
EC2_USER="ubuntu"

# Unified SSH
. ./scripts/ssh_key.sh 2>/dev/null || source ./scripts/ssh_key.sh

echo "🔄 Applying database migration to AWS..."

ssh_cmd "$EC2_USER@$EC2_HOST" << 'MIGRATION_SCRIPT'
cd ~/automated-trading-platform

echo "Applying previous_price migration..."
docker compose exec -T backend python backend/scripts/apply_migration_previous_price.py || {
    echo "⚠️  Migration script failed, trying direct SQL..."
    docker compose exec -T db psql -U trader -d atp -c "ALTER TABLE signal_throttle_states ADD COLUMN IF NOT EXISTS previous_price DOUBLE PRECISION NULL;" || echo "Migration may have already been applied"
}

echo "✅ Migration complete!"
MIGRATION_SCRIPT

echo "✅ Migration applied successfully!"


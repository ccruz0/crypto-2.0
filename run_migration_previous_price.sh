#!/bin/bash
# Script to run the previous_price migration on AWS server

set -e

EC2_HOST="54.254.150.31"
EC2_USER="ubuntu"
. ./scripts/ssh_key.sh 2>/dev/null || source ./scripts/ssh_key.sh

echo "🔄 Running migration: Add previous_price column to signal_throttle_states"
echo ""

# Copy migration file to server
echo "📦 Copying migration file to server..."
scp_cmd backend/migrations/add_previous_price_to_signal_throttle.sql "$EC2_USER@$EC2_HOST:~/migration.sql"

# Execute migration using Docker
echo "🚀 Executing migration on server..."
ssh_cmd "$EC2_USER@$EC2_HOST" << 'MIGRATION_SCRIPT'
cd ~/automated-trading-platform

# Execute migration using docker compose exec
if docker compose --profile aws ps db | grep -q "Up"; then
    echo "Executing migration via Docker..."
    docker compose --profile aws exec -T db psql -U trader -d atp < ~/migration.sql
    echo "✅ Migration completed successfully"
else
    echo "❌ Database container is not running"
    echo "Available containers:"
    docker compose --profile aws ps
    exit 1
fi

# Clean up
rm -f ~/migration.sql
MIGRATION_SCRIPT

echo ""
echo "✅ Migration execution complete!"


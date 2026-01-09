#!/bin/bash
# Script to run the decision tracing migration on AWS
# This script can be run on the AWS server or locally to trigger remote execution

set -e

echo "=" | tr -d '\n'
for i in {1..80}; do echo -n "="; done
echo ""
echo "DECISION TRACING MIGRATION SCRIPT"
echo "=" | tr -d '\n'
for i in {1..80}; do echo -n "="; done
echo ""
echo ""

# Default values (can be overridden by environment variables)
EC2_HOST="${EC2_HOST:-47.130.143.159}"
EC2_USER="${EC2_USER:-ubuntu}"
PROJECT_DIR="${PROJECT_DIR:-automated-trading-platform}"

# Source SSH key helper if available
if [ -f "./scripts/ssh_key.sh" ]; then
    . ./scripts/ssh_key.sh
fi

# Check if we're running on AWS server or locally
IS_AWS_SERVER=false
if [ -f "/etc/cloud/cloud-init.log" ] || [ -n "${AWS_EXECUTION_ENV}" ] || hostname | grep -q "ip-"; then
    IS_AWS_SERVER=true
    echo "✅ Running on AWS server (detected)"
else
    echo "ℹ️  Running locally (will SSH to AWS)"
fi

run_migration_local() {
    echo ""
    echo "Step 1: Checking if migration script exists..."
    MIGRATION_FILE="backend/migrations/add_decision_tracing_fields.sql"
    
    if [ ! -f "$MIGRATION_FILE" ]; then
        echo "❌ ERROR: Migration file not found: $MIGRATION_FILE"
        exit 1
    fi
    
    echo "✅ Migration file found: $MIGRATION_FILE"
    
    echo ""
    echo "Step 2: Checking if database is accessible..."
    
    # Check if Docker is running
    if ! docker compose --profile aws ps db > /dev/null 2>&1; then
        echo "❌ ERROR: Docker is not running or 'db' service is not up"
        echo "   Please start the database service first:"
        echo "   docker compose --profile aws up -d db"
        exit 1
    fi
    
    echo "✅ Database service is running"
    
    echo ""
    echo "Step 3: Running migration via Docker..."
    
    # Copy migration file to container if needed, or run directly
    docker compose --profile aws exec -T db psql -U trader -d atp < "$MIGRATION_FILE" 2>&1 | tee /tmp/migration_output.log
    
    MIGRATION_EXIT_CODE=${PIPESTATUS[0]}
    
    if [ $MIGRATION_EXIT_CODE -eq 0 ]; then
        echo ""
        echo "✅ Migration completed successfully!"
    else
        echo ""
        echo "❌ ERROR: Migration failed with exit code $MIGRATION_EXIT_CODE"
        echo "   Check /tmp/migration_output.log for details"
        exit 1
    fi
    
    echo ""
    echo "Step 4: Verifying migration..."
    
    # Verify columns exist
    VERIFY_QUERY="
    SELECT 
        column_name, 
        data_type, 
        is_nullable
    FROM information_schema.columns 
    WHERE table_name = 'telegram_messages' 
    AND column_name IN ('decision_type', 'reason_code', 'reason_message', 'context_json', 'exchange_error_snippet', 'correlation_id')
    ORDER BY column_name;
    "
    
    echo "Running verification query..."
    docker compose --profile aws exec -T db psql -U trader -d atp -c "$VERIFY_QUERY" 2>&1
    
    echo ""
    echo "Step 5: Checking message statistics..."
    
    # Check if there are any messages with decision_type
    STATS_QUERY="
    SELECT 
        COUNT(*) as total_messages,
        COUNT(CASE WHEN blocked = true THEN 1 END) as blocked_messages,
        COUNT(CASE WHEN decision_type IS NOT NULL THEN 1 END) as messages_with_decision_type,
        COUNT(CASE WHEN reason_code IS NOT NULL THEN 1 END) as messages_with_reason_code
    FROM telegram_messages;
    "
    
    echo "Getting message statistics..."
    docker compose --profile aws exec -T db psql -U trader -d atp -c "$STATS_QUERY" 2>&1
    
    echo ""
    echo "=" | tr -d '\n'
    for i in {1..80}; do echo -n "="; done
    echo ""
    echo "✅ MIGRATION COMPLETE!"
    echo "=" | tr -d '\n'
    for i in {1..80}; do echo -n "="; done
    echo ""
    echo ""
    echo "Next steps:"
    echo "1. Restart backend service: docker compose --profile aws restart backend-aws"
    echo "2. Check backend logs: docker compose --profile aws logs -n 50 backend-aws | grep -i 'decision\|migration'"
    echo "3. Run diagnostic script: python3 backend/scripts/check_decision_tracing.py"
    echo ""
}

run_migration_remote() {
    echo ""
    echo "Connecting to AWS server: $EC2_USER@$EC2_HOST"
    echo ""
    
    # Check SSH connection
    if ! ssh -o ConnectTimeout=5 -o BatchMode=yes "${EC2_USER}@${EC2_HOST}" exit 2>/dev/null; then
        echo "❌ ERROR: Cannot connect to AWS server"
        echo "   Please ensure:"
        echo "   - SSH key is configured correctly"
        echo "   - Server is accessible: $EC2_HOST"
        echo "   - User has access: $EC2_USER"
        exit 1
    fi
    
    echo "✅ SSH connection successful"
    
    # Run migration remotely
    ssh "${EC2_USER}@${EC2_HOST}" << ENDSSH
set -e

cd ~/$PROJECT_DIR || cd /home/ubuntu/$PROJECT_DIR || { echo "❌ Cannot find project directory" && exit 1; }

echo ""
echo "Running migration on AWS server..."
echo ""

# Check if migration file exists
if [ ! -f "backend/migrations/add_decision_tracing_fields.sql" ]; then
    echo "❌ ERROR: Migration file not found on server"
    exit 1
fi

# Check if Docker is running
if ! docker compose --profile aws ps db > /dev/null 2>&1; then
    echo "❌ ERROR: Docker is not running or 'db' service is not up"
    echo "   Attempting to start database service..."
    docker compose --profile aws up -d db || { echo "Failed to start db service" && exit 1; }
    echo "   Waiting for database to be ready..."
    sleep 10
fi

# Run migration
echo "Running migration..."
docker compose --profile aws exec -T db psql -U trader -d atp < backend/migrations/add_decision_tracing_fields.sql

MIGRATION_EXIT_CODE=\$?
if [ \$MIGRATION_EXIT_CODE -ne 0 ]; then
    echo "❌ Migration failed with exit code \$MIGRATION_EXIT_CODE"
    exit 1
fi

echo ""
echo "✅ Migration completed successfully!"

# Verify migration
echo ""
echo "Verifying migration..."
VERIFY_QUERY="
SELECT 
    column_name, 
    data_type, 
    is_nullable
FROM information_schema.columns 
WHERE table_name = 'telegram_messages' 
AND column_name IN ('decision_type', 'reason_code', 'reason_message', 'context_json', 'exchange_error_snippet', 'correlation_id')
ORDER BY column_name;
"

docker compose --profile aws exec -T db psql -U trader -d atp -c "\$VERIFY_QUERY"

echo ""
echo "Checking message statistics..."
STATS_QUERY="
SELECT 
    COUNT(*) as total_messages,
    COUNT(CASE WHEN blocked = true THEN 1 END) as blocked_messages,
    COUNT(CASE WHEN decision_type IS NOT NULL THEN 1 END) as messages_with_decision_type,
    COUNT(CASE WHEN reason_code IS NOT NULL THEN 1 END) as messages_with_reason_code
FROM telegram_messages;
"

docker compose --profile aws exec -T db psql -U trader -d atp -c "\$STATS_QUERY"

echo ""
echo "✅ Migration verification complete!"
ENDSSH

    if [ $? -eq 0 ]; then
        echo ""
        echo "=" | tr -d '\n'
        for i in {1..80}; do echo -n "="; done
        echo ""
        echo "✅ MIGRATION COMPLETE ON AWS!"
        echo "=" | tr -d '\n'
        for i in {1..80}; do echo -n "="; done
        echo ""
        echo ""
        echo "Next steps (on AWS server):"
        echo "1. Restart backend: docker compose --profile aws restart backend-aws"
        echo "2. Check logs: docker compose --profile aws logs -n 50 backend-aws | grep -i 'decision'"
        echo "3. Run diagnostic: python3 backend/scripts/check_decision_tracing.py"
        echo ""
    else
        echo ""
        echo "❌ Migration failed remotely. Check the output above for details."
        exit 1
    fi
}

# Main execution
if [ "$IS_AWS_SERVER" = true ]; then
    run_migration_local
else
    run_migration_remote
fi


#!/bin/bash
set -euo pipefail

# Helper script to view backend logs on AWS without hard-coding container name
# Usage: bash scripts/aws_backend_logs.sh [docker logs arguments]
# Example: bash scripts/aws_backend_logs.sh --tail 200 -f

REMOTE_HOST="hilovivo-aws"
REMOTE_PATH="/home/ubuntu/automated-trading-platform"

# Detect backend container name dynamically
CONTAINER_NAME=$(ssh "$REMOTE_HOST" "cd $REMOTE_PATH && docker ps --format '{{.Names}}' | grep -E 'automated-trading-platform-backend' | head -1")

if [ -z "$CONTAINER_NAME" ]; then
    echo "Error: No backend container found matching 'automated-trading-platform-backend'" >&2
    echo "Available containers:" >&2
    ssh "$REMOTE_HOST" "cd $REMOTE_PATH && docker ps --format 'table {{.Names}}'" >&2
    exit 1
fi

# Forward all arguments to docker logs
# Build the command array and pass it properly
ARGS=()
for arg in "$@"; do
    ARGS+=("$arg")
done

# Construct the docker logs command
if [ ${#ARGS[@]} -eq 0 ]; then
    ssh "$REMOTE_HOST" "cd $REMOTE_PATH && docker logs \"$CONTAINER_NAME\""
else
    # Use printf to properly quote arguments
    QUOTED_ARGS=$(printf "'%s' " "${ARGS[@]}")
    ssh "$REMOTE_HOST" "cd $REMOTE_PATH && docker logs \"$CONTAINER_NAME\" $QUOTED_ARGS"
fi


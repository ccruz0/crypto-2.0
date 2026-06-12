#!/bin/bash

# Start AWS Environment
echo "Starting AWS environment..."

# Set environment variables
export ENVIRONMENT=aws
export NODE_ENV=production

# Start services with AWS profile
bash scripts/verify_clean_worktree.sh --frontend-only
docker compose --profile aws up -d --build

echo "AWS environment started!"
echo "Backend: http://54.254.150.31:8000"
echo "Frontend: http://54.254.150.31:3000"


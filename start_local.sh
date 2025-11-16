#!/bin/bash

# Start Local Development Environment
echo "Starting local development environment..."

# Set environment variables
export ENVIRONMENT=local
export NODE_ENV=development

# Start services with local profile
docker compose --profile local up -d --build

echo "Local development environment started!"
echo "Backend: http://localhost:8000"
echo "Frontend: http://localhost:3000"
echo "Database: localhost:5432"


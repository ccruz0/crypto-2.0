#!/bin/bash
# Script to update Dockerfile on AWS server via SSM

INSTANCE_ID="i-08726dc37133b2454"
REGION="ap-southeast-1"
PROJECT_DIR="/home/ubuntu/automated-trading-platform"

# Read Dockerfile and encode to base64
DOCKERFILE_B64=$(cat backend/Dockerfile | base64)

# Create command to write Dockerfile
COMMAND="echo '$DOCKERFILE_B64' | base64 -d > $PROJECT_DIR/backend/Dockerfile && echo 'Dockerfile updated'"

# Send command via SSM
COMMAND_ID=$(aws ssm send-command \
    --instance-ids "$INSTANCE_ID" \
    --region "$REGION" \
    --document-name "AWS-RunShellScript" \
    --parameters "commands=[\"$COMMAND\"]" \
    --query 'Command.CommandId' \
    --output text)

echo "Command ID: $COMMAND_ID"
echo "Waiting for command to complete..."
sleep 10

# Get output
OUTPUT=$(aws ssm get-command-invocation \
    --instance-id "$INSTANCE_ID" \
    --region "$REGION" \
    --command-id "$COMMAND_ID" \
    --query 'StandardOutputContent' \
    --output text)

echo "$OUTPUT"




